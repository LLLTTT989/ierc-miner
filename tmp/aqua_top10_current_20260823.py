#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import math
import statistics
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
from decimal import Decimal, getcontext

import requests

getcontext().prec = 100
MERKL = "https://api.merkl.xyz/v4"
MCP = "https://api.1inch.com/mcp/protocol"
ANCHOR = "0xe01ecff2f6c4f2416e83e6861e8abf79b1c95950"
NOW = datetime.now(timezone.utc)
CUTOFF = int((NOW - timedelta(days=7)).timestamp())
SEASON_START_LO = 1785100000
SEASON_START_HI = 1785400000
SEASON_END_LO = 1792900000
SEASON_END_HI = 1793400000

http = requests.Session()
http.headers.update({"user-agent": "aqua-top10-current/2026-08-23", "accept": "application/json"})


def get_json(url, params=None, tries=7):
    last = None
    for i in range(tries):
        try:
            response = http.get(url, params=params, timeout=90)
            print("HTTP_GET|status=%s|url=%s" % (response.status_code, response.url), flush=True)
            if response.status_code == 429 or response.status_code >= 500:
                time.sleep(min(8, i + 1))
                continue
            response.raise_for_status()
            return response.json()
        except Exception as exc:
            last = exc
            time.sleep(min(8, i + 1))
    raise last


def rows(data):
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("items", "data", "campaigns", "opportunities", "rewards"):
            if isinstance(data.get(key), list):
                return data[key]
    return []


def paged(path, base=None, max_pages=80):
    base = dict(base or {})
    output = []
    for page in range(max_pages):
        data = get_json(MERKL + path, {**base, "page": page})
        batch = rows(data)
        if not batch:
            break
        output.extend(batch)
        if len(batch) < int(base.get("items", 1000)):
            break
    return output


def walk(value, path="root"):
    if isinstance(value, dict):
        yield path, value
        for key, child in value.items():
            yield from walk(child, path + "." + str(key))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from walk(child, path + "[%d]" % index)


def token_obj(obj):
    if not isinstance(obj, dict):
        return {}
    for key in ("rewardToken", "token"):
        value = obj.get(key)
        if isinstance(value, dict):
            return value
    return {}


def opportunity_name(obj):
    if not isinstance(obj, dict):
        return ""
    opportunity = obj.get("opportunity")
    if isinstance(opportunity, dict):
        return str(opportunity.get("name") or opportunity.get("description") or opportunity.get("id") or "")
    return str(obj.get("opportunityName") or obj.get("name") or "")


def user_address(value):
    if isinstance(value, str):
        return value.lower()
    if isinstance(value, dict):
        for key in ("address", "user", "recipient", "hash", "addressHash"):
            candidate = value.get(key)
            if isinstance(candidate, str):
                return candidate.lower()
    return ""


def human_amount(value, decimals):
    if value is None:
        return Decimal(0)
    text = str(value)
    try:
        amount = Decimal(text)
    except Exception:
        return Decimal(0)
    if "." in text or "e" in text.lower():
        return amount
    return amount / (Decimal(10) ** decimals)


def discover_campaigns():
    campaign_ids = set()
    for params in ({}, {"chainId": "1", "reloadChainId": "1"}):
        try:
            data = get_json(MERKL + "/users/%s/rewards" % ANCHOR, params)
        except Exception as exc:
            print("ANCHOR_REWARD_FAIL|params=%s|error=%r" % (params, exc), flush=True)
            continue
        for _, obj in walk(data):
            campaign_id = obj.get("campaignId") or obj.get("campaign_id")
            if isinstance(campaign_id, str) and campaign_id.startswith("0x") and len(campaign_id) == 66:
                campaign_ids.add(campaign_id.lower())

    print("ANCHOR_CAMPAIGN_IDS|count=%s" % len(campaign_ids), flush=True)
    candidates = []
    for campaign_id in sorted(campaign_ids):
        try:
            candidates.extend(paged("/campaigns", {"campaignId": campaign_id, "withOpportunity": "true", "items": 100}, 3))
        except Exception as exc:
            print("CAMPAIGN_LOOKUP_FAIL|cid=%s|error=%r" % (campaign_id, exc), flush=True)

    for symbol in ("1INCH", "USDC"):
        try:
            candidates.extend(paged("/campaigns", {"tokenSymbol": symbol, "withOpportunity": "true", "items": 1000}, 10))
        except Exception as exc:
            print("CAMPAIGN_SEARCH_FAIL|symbol=%s|error=%r" % (symbol, exc), flush=True)

    campaigns = {}
    for campaign in candidates:
        if not isinstance(campaign, dict):
            continue
        campaign_id = str(campaign.get("campaignId") or "").lower()
        if not (campaign_id.startswith("0x") and len(campaign_id) == 66):
            continue
        reward_token = token_obj(campaign)
        symbol = str(reward_token.get("symbol") or campaign.get("tokenSymbol") or "").upper()
        if symbol not in ("1INCH", "USDC"):
            continue
        start = int(campaign.get("startTimestamp") or campaign.get("start") or 0)
        end = int(campaign.get("endTimestamp") or campaign.get("end") or 0)
        blob = json.dumps(campaign, ensure_ascii=False).lower()
        is_dates = SEASON_START_LO <= start <= SEASON_START_HI and SEASON_END_LO <= end <= SEASON_END_HI
        is_aqua = "aqua" in blob or ("1inch" in blob and is_dates)
        if not (is_dates and is_aqua):
            continue
        chain = int(campaign.get("distributionChainId") or campaign.get("chainId") or 1)
        decimals = int(reward_token.get("decimals") or (6 if symbol == "USDC" else 18))
        key = (chain, campaign_id, symbol)
        campaigns[key] = {
            "chain": chain,
            "cid": campaign_id,
            "symbol": symbol,
            "decimals": decimals,
            "name": opportunity_name(campaign),
            "start": start,
            "end": end,
        }

    result = sorted(campaigns.values(), key=lambda item: (item["name"], item["symbol"], item["chain"], item["cid"]))
    print("AQUA_CAMPAIGNS|count=%s" % len(result), flush=True)
    for campaign in result:
        print("CAMPAIGN|name=%s|symbol=%s|chain=%s|cid=%s" % (campaign["name"], campaign["symbol"], campaign["chain"], campaign["cid"]), flush=True)
    return result


def build_ranking(campaigns):
    totals = defaultdict(lambda: {"1INCH": Decimal(0), "USDC": Decimal(0), "categories": defaultdict(lambda: {"1INCH": Decimal(0), "USDC": Decimal(0)})})
    for campaign in campaigns:
        reward_rows = paged("/rewards", {"items": 1000, "chainId": campaign["chain"], "campaignId": campaign["cid"]}, 80)
        parsed = 0
        for row in reward_rows:
            if not isinstance(row, dict):
                continue
            address = user_address(row.get("user") or row.get("address") or row.get("recipient"))
            if not (address.startswith("0x") and len(address) == 42):
                continue
            amount = human_amount(row.get("amount") or row.get("reward") or row.get("value"), campaign["decimals"])
            pending = human_amount(row.get("pending"), campaign["decimals"])
            total = amount + pending
            if total <= 0:
                continue
            totals[address][campaign["symbol"]] += total
            totals[address]["categories"][campaign["name"]][campaign["symbol"]] += total
            parsed += 1
        print("REWARD_ROWS|name=%s|symbol=%s|users=%s" % (campaign["name"], campaign["symbol"], parsed), flush=True)

    ranking = [(data["1INCH"], data["USDC"], address, data["categories"]) for address, data in totals.items()]
    ranking.sort(key=lambda item: (item[0], item[1]), reverse=True)
    for rank, (one_inch, usdc, address, _) in enumerate(ranking[:20], 1):
        print("RANK|rank=%s|address=%s|one=%s|usdc=%s" % (rank, address, one_inch, usdc), flush=True)
    return ranking


class McpClient:
    def __init__(self):
        self.http = requests.Session()
        self.http.headers.update({"accept": "application/json, text/event-stream", "content-type": "application/json", "user-agent": "aqua-top10-current/2026-08-23"})
        self.session_id = None
        self.request_id = 0
        self.protocol_version = "2025-11-25"

    @staticmethod
    def parse_response(body, content_type, expected_id):
        body = body.replace("\r\n", "\n").strip()
        messages = []
        if "text/event-stream" in (content_type or "").lower() or body.startswith("data:"):
            for block in body.split("\n\n"):
                data_lines = [line[5:].lstrip() for line in block.split("\n") if line.startswith("data:")]
                if not data_lines:
                    continue
                payload = "\n".join(data_lines)
                if payload == "[DONE]":
                    continue
                messages.append(json.loads(payload))
        else:
            value = json.loads(body)
            messages = value if isinstance(value, list) else [value]
        for message in messages:
            if str(message.get("id")) == str(expected_id):
                return message
        raise RuntimeError("missing MCP response id=%s" % expected_id)

    def post(self, method, params, notify=False, tries=8):
        if notify:
            payload = {"jsonrpc": "2.0", "method": method, "params": params}
            expected = None
        else:
            self.request_id += 1
            expected = self.request_id
            payload = {"jsonrpc": "2.0", "id": expected, "method": method, "params": params}
        last = None
        for attempt in range(tries):
            headers = {"MCP-Protocol-Version": self.protocol_version}
            if self.session_id:
                headers["Mcp-Session-Id"] = self.session_id
            try:
                response = self.http.post(MCP, json=payload, headers=headers, timeout=120)
                print("MCP_HTTP|method=%s|status=%s" % (method, response.status_code), flush=True)
                if response.status_code == 429 or response.status_code >= 500:
                    time.sleep(min(10, attempt + 1))
                    continue
                response.raise_for_status()
                if response.headers.get("mcp-session-id"):
                    self.session_id = response.headers["mcp-session-id"]
                if notify:
                    return None
                envelope = self.parse_response(response.text, response.headers.get("content-type", ""), expected)
                if envelope.get("error"):
                    raise RuntimeError(envelope["error"])
                return envelope.get("result")
            except Exception as exc:
                last = exc
                print("MCP_RETRY|method=%s|attempt=%s|error=%r" % (method, attempt + 1, exc), flush=True)
                time.sleep(min(10, attempt + 1))
        raise last

    def initialize(self):
        result = self.post("initialize", {"protocolVersion": self.protocol_version, "capabilities": {}, "clientInfo": {"name": "aqua-top10-current", "version": "1.0"}})
        if isinstance(result, dict) and result.get("protocolVersion"):
            self.protocol_version = str(result["protocolVersion"])
        self.post("notifications/initialized", {}, notify=True)

    def aqua(self, arguments):
        result = self.post("tools/call", {"name": "aqua", "arguments": arguments})
        if isinstance(result, dict) and result.get("isError"):
            raise RuntimeError(result)
        if isinstance(result, dict) and result.get("structuredContent") is not None:
            return result["structuredContent"]
        parsed = []
        for item in (result.get("content") if isinstance(result, dict) else []) or []:
            text = item.get("text") if isinstance(item, dict) else None
            if isinstance(text, str):
                try:
                    parsed.append(json.loads(text))
                except Exception:
                    pass
        if len(parsed) == 1:
            return parsed[0]
        return parsed or result


def volume7(item):
    try:
        return float(item.get("performance", {}).get("volume", {}).get("last7d", {}).get("usd") or 0)
    except Exception:
        return 0.0


def fees7(item):
    try:
        return float(item.get("performance", {}).get("fees", {}).get("last7d", {}).get("usd") or 0)
    except Exception:
        return 0.0


def fetch_strategies(client, address, status):
    output = []
    cursor = None
    seen = set()
    for page in range(35):
        arguments = {"action": "list_maker_strategies", "address": address, "status": [status], "limit": 100}
        if cursor:
            arguments["cursor"] = cursor
        data = client.aqua(arguments)
        items = data.get("items") if isinstance(data, dict) else []
        print("STRATEGY_PAGE|address=%s|status=%s|page=%s|items=%s" % (address, status, page + 1, len(items or [])), flush=True)
        if not items:
            break
        output.extend(items)
        cursor = data.get("nextCursor") if isinstance(data, dict) else None
        if not cursor or cursor in seen:
            break
        seen.add(cursor)
        if status == "closed" and all(int(item.get("closedAt") or 0) < CUTOFF and int(item.get("openedAt") or 0) < CUTOFF and volume7(item) == 0 for item in items):
            break
    return output


def decode_range(item):
    try:
        encoded = bytes.fromhex(str(item["strategyBytes"]).removeprefix("0x"))
        length = int.from_bytes(encoded[128:160], "big")
        program = encoded[160:160 + length]
        if len(program) < 114:
            return None
        first = int.from_bytes(program[50:82], "big")
        second = int.from_bytes(program[82:114], "big")
        if first <= 0 or second <= 0:
            return None
        lo, hi = min(first, second), max(first, second)
        raw_lo = (Decimal(lo) / Decimal(10 ** 18)) ** 2
        raw_hi = (Decimal(hi) / Decimal(10 ** 18)) ** 2
        tokens = item.get("tokens") or []
        if len(tokens) < 2:
            return None
        token0, token1 = tokens[0], tokens[1]
        address0 = str(token0.get("address") or "").lower()
        address1 = str(token1.get("address") or "").lower()
        decimals0 = int((token0.get("meta") or {}).get("decimals") or 18)
        decimals1 = int((token1.get("meta") or {}).get("decimals") or 18)
        symbol0 = str((token0.get("meta") or {}).get("symbol") or address0)
        symbol1 = str((token1.get("meta") or {}).get("symbol") or address1)
        if int(address0, 16) < int(address1, 16):
            price_min = raw_lo * (Decimal(10) ** (decimals0 - decimals1))
            price_max = raw_hi * (Decimal(10) ** (decimals0 - decimals1))
        else:
            inverse_min = raw_lo * (Decimal(10) ** (decimals1 - decimals0))
            inverse_max = raw_hi * (Decimal(10) ** (decimals1 - decimals0))
            price_min = Decimal(1) / inverse_max
            price_max = Decimal(1) / inverse_min
        midpoint = (price_min + price_max) / 2
        width = (price_max - price_min) / midpoint * Decimal(100) if midpoint else None
        return {
            "pair": symbol0 + "/" + symbol1,
            "quote": symbol1,
            "min": str(price_min),
            "max": str(price_max),
            "mid": str(midpoint),
            "widthPct": float(width),
        }
    except Exception as exc:
        return {"error": repr(exc)}


def quantile(values, fraction):
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    low = math.floor(position)
    high = math.ceil(position)
    return ordered[low] if low == high else ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def classify(summary):
    median_width = summary["widthMedianPct"]
    opened = summary["opened7d"]
    active = summary["openCount"]
    pair_medians = [pair["medianWidthPct"] for pair in summary["pairs"] if pair["medianWidthPct"] is not None]
    narrow = any(value < 0.10 for value in pair_medians)
    wide = any(value > 3 for value in pair_medians)
    if opened >= 250 and median_width is not None and median_width < 0.10:
        return "极限微区间 HFT"
    if opened >= 200 and narrow and wide:
        return "多层杠铃型高频做市"
    if opened >= 200 and median_width is not None and median_width < 0.80:
        return "高频窄区间做市"
    if opened < 20 and median_width is not None and median_width > 3:
        return "宽区间低频库存型"
    if active == 0 and opened < 10:
        return "已退出或仅剩历史成交"
    if narrow and wide:
        return "风险分层混合型"
    if median_width is not None and median_width <= 1.5:
        return "中频标准区间做市"
    return "中宽区间混合型"


def analyze_address(client, rank, one_inch, usdc, address):
    print("STRATEGY_START|rank=%s|address=%s" % (rank, address), flush=True)
    raw = fetch_strategies(client, address, "open") + fetch_strategies(client, address, "closed")
    unique = {}
    for item in raw:
        unique[(item.get("chainId"), item.get("app"), item.get("strategyHash"))] = item

    strategy_rows = []
    for item in unique.values():
        opened = int(item.get("openedAt") or 0)
        closed = int(item.get("closedAt") or 0)
        is_open = not item.get("closedAt")
        if not (is_open or opened >= CUTOFF or closed >= CUTOFF or volume7(item) > 0):
            continue
        decoded = decode_range(item) or {}
        tokens = item.get("tokens") or []
        pair = decoded.get("pair") or "/".join(str((token.get("meta") or {}).get("symbol") or "?") for token in tokens[:2])
        strategy_rows.append({
            "chainId": int(item.get("chainId") or 0),
            "strategyHash": item.get("strategyHash"),
            "openedAt": opened,
            "closedAt": item.get("closedAt"),
            "status": "open" if is_open else "closed",
            "pair": pair,
            "quote": decoded.get("quote"),
            "rangeMin": decoded.get("min"),
            "rangeMax": decoded.get("max"),
            "widthPct": decoded.get("widthPct"),
            "feePercent": (item.get("classification") or {}).get("feePercent"),
            "state": (item.get("classification") or {}).get("state"),
            "volume7dUsd": volume7(item),
            "fees7dUsd": fees7(item),
        })
    strategy_rows.sort(key=lambda row: row["openedAt"], reverse=True)

    grouped = defaultdict(list)
    for row in strategy_rows:
        grouped[(row["chainId"], row["pair"])].append(row)

    pairs = []
    for (chain, pair), group in grouped.items():
        widths = [row["widthPct"] for row in group if row["widthPct"] is not None]
        latest = max(group, key=lambda row: row["openedAt"])
        pairs.append({
            "chainId": chain,
            "pair": pair,
            "strategies": len(group),
            "open": sum(row["status"] == "open" for row in group),
            "opened7d": sum(row["openedAt"] >= CUTOFF for row in group),
            "closed7d": sum(bool(row["closedAt"]) and int(row["closedAt"]) >= CUTOFF for row in group),
            "volume7dUsd": sum(row["volume7dUsd"] for row in group),
            "fees7dUsd": sum(row["fees7dUsd"] for row in group),
            "medianWidthPct": statistics.median(widths) if widths else None,
            "p25WidthPct": quantile(widths, 0.25),
            "p75WidthPct": quantile(widths, 0.75),
            "minWidthPct": min(widths) if widths else None,
            "maxWidthPct": max(widths) if widths else None,
            "feeTiers": dict(Counter(str(row["feePercent"]) for row in group)),
            "latest": latest,
        })
    pairs.sort(key=lambda pair: (pair["volume7dUsd"], pair["strategies"]), reverse=True)

    widths_all = [row["widthPct"] for row in strategy_rows if row["widthPct"] is not None]
    summary = {
        "rank": rank,
        "address": address,
        "rewardOneInch": str(one_inch),
        "rewardUsdc": str(usdc),
        "strategyCount": len(strategy_rows),
        "openCount": sum(row["status"] == "open" for row in strategy_rows),
        "opened7d": sum(row["openedAt"] >= CUTOFF for row in strategy_rows),
        "closed7d": sum(bool(row["closedAt"]) and int(row["closedAt"]) >= CUTOFF for row in strategy_rows),
        "volume7dUsd": sum(row["volume7dUsd"] for row in strategy_rows),
        "fees7dUsd": sum(row["fees7dUsd"] for row in strategy_rows),
        "widthMedianPct": statistics.median(widths_all) if widths_all else None,
        "widthP25Pct": quantile(widths_all, 0.25),
        "widthP75Pct": quantile(widths_all, 0.75),
        "chainCounts": dict(Counter(row["chainId"] for row in strategy_rows)),
        "pairs": pairs,
        "latestOpen": [row for row in strategy_rows if row["status"] == "open"][:20],
        "rows": strategy_rows,
    }
    summary["archetype"] = classify(summary)
    print(
        "SUMMARY|rank=%s|address=%s|type=%s|strategies=%s|open=%s|opened7d=%s|closed7d=%s|volume7d=%.2f|medianWidth=%s|pairs=%s"
        % (
            rank,
            address,
            summary["archetype"],
            summary["strategyCount"],
            summary["openCount"],
            summary["opened7d"],
            summary["closed7d"],
            summary["volume7dUsd"],
            summary["widthMedianPct"],
            ",".join(
                "%s@%s:v%.0f:w%s:o%s"
                % (
                    pair["pair"],
                    pair["chainId"],
                    pair["volume7dUsd"],
                    "%.4f" % pair["medianWidthPct"] if pair["medianWidthPct"] is not None else "-",
                    pair["open"],
                )
                for pair in pairs[:8]
            ),
        ),
        flush=True,
    )
    return summary


def make_markdown(result):
    lines = [
        "# Aqua Season 1 当前前十策略（2026-08-23）",
        "",
        "快照 UTC：`%s`；滚动 7 日起点：`%s`。" % (result["snapshotUtc"], result["cutoffUtc"]),
        "",
        "## 当前奖励汇总排名",
        "",
        "| 排名 | 地址 | 1INCH（amount+pending） | USDC（amount+pending） |",
        "|---:|---|---:|---:|",
    ]
    for row in result["ranking"]:
        lines.append("| %s | `%s` | %s | %s |" % (row["rank"], row["address"], row["oneInch"], row["usdc"]))

    lines.extend([
        "",
        "## 地址策略摘要",
        "",
        "| 排名 | 地址 | 策略类型 | 近7日新开/关闭 | 当前开放 | 近7日成交量 | 区间中位宽度 | 主要币对 |",
        "|---:|---|---|---:|---:|---:|---:|---|",
    ])
    for address in result["addresses"]:
        if address.get("error"):
            lines.append("| %s | `%s` | 查询失败 | - | - | - | - | %s |" % (address["rank"], address["address"], address["error"]))
            continue
        top_pairs = "; ".join(
            "%s(c%s): $%.0f / 中位宽 %.4f%% / 开 %s"
            % (pair["pair"], pair["chainId"], pair["volume7dUsd"], pair["medianWidthPct"] or 0, pair["open"])
            for pair in address["pairs"][:6]
        )
        lines.append(
            "| %s | `%s` | %s | %s / %s | %s | $%.2f | %s%% | %s |"
            % (
                address["rank"],
                address["address"],
                address["archetype"],
                address["opened7d"],
                address["closed7d"],
                address["openCount"],
                address["volume7dUsd"],
                "%.4f" % address["widthMedianPct"] if address["widthMedianPct"] is not None else "-",
                top_pairs,
            )
        )

        lines.extend([
            "",
            "### #%s `%s` — %s" % (address["rank"], address["address"], address["archetype"]),
            "",
            "- 近 7 日新开 `%s`、关闭 `%s`，当前开放 `%s`，策略成交量 `$%.2f`。"
            % (address["opened7d"], address["closed7d"], address["openCount"], address["volume7dUsd"]),
            "- 区间宽度中位数 `%s%%`；P25–P75 为 `%s%%–%s%%`。"
            % (
                "%.6f" % address["widthMedianPct"] if address["widthMedianPct"] is not None else "-",
                "%.6f" % address["widthP25Pct"] if address["widthP25Pct"] is not None else "-",
                "%.6f" % address["widthP75Pct"] if address["widthP75Pct"] is not None else "-",
            ),
            "- 主要币对：",
        ])
        for pair in address["pairs"][:10]:
            latest = pair["latest"]
            lines.append(
                "  - `%s`（chain %s）：近 7 日 `$%.2f`，策略 `%s` 条/开放 `%s`，区间中位 `%s%%`，最新区间 `%s–%s`，费率档 `%s`。"
                % (
                    pair["pair"],
                    pair["chainId"],
                    pair["volume7dUsd"],
                    pair["strategies"],
                    pair["open"],
                    "%.6f" % pair["medianWidthPct"] if pair["medianWidthPct"] is not None else "-",
                    latest.get("rangeMin") or "-",
                    latest.get("rangeMax") or "-",
                    pair["feeTiers"],
                )
            )
    return "\n".join(lines) + "\n"


def main():
    campaigns = discover_campaigns()
    if len(campaigns) < 12:
        raise RuntimeError("Aqua Season 1 campaigns discovered too few: %s" % len(campaigns))
    ranking = build_ranking(campaigns)
    top10 = ranking[:10]
    if len(top10) < 10:
        raise RuntimeError("Current ranking returned only %s addresses" % len(top10))

    client = McpClient()
    client.initialize()
    result = {
        "snapshotUtc": NOW.isoformat(),
        "cutoffUtc": datetime.fromtimestamp(CUTOFF, timezone.utc).isoformat(),
        "campaignCount": len(campaigns),
        "ranking": [],
        "addresses": [],
    }

    for rank, (one_inch, usdc, address, _) in enumerate(top10, 1):
        result["ranking"].append({"rank": rank, "address": address, "oneInch": str(one_inch), "usdc": str(usdc)})
        try:
            result["addresses"].append(analyze_address(client, rank, one_inch, usdc, address))
        except Exception as exc:
            print("ADDRESS_FAIL|rank=%s|address=%s|error=%r" % (rank, address, exc), flush=True)
            result["addresses"].append({"rank": rank, "address": address, "error": repr(exc)})

    with open("aqua_top10_current_20260823.json", "w", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)
    with open("aqua_top10_current_20260823.md", "w", encoding="utf-8") as handle:
        handle.write(make_markdown(result))


if __name__ == "__main__":
    main()
