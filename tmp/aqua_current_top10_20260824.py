#!/usr/bin/env python3
from __future__ import annotations

import json
import math
import statistics
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal, getcontext
from pathlib import Path
from typing import Any

import requests

getcontext().prec = 100

MERKL = "https://api.merkl.xyz/v4"
MCP = "https://api.1inch.com/mcp/protocol"
MCP_VERSION = "2025-11-25"
ANCHORS = [
    "0xe01ecff2f6c4f2416e83e6861e8abf79b1c95950",
    "0xe22259232b3cf5c74104cf2ded7f878f0201b198",
    "0xf5947f530b2a67b3d9ef211c10abba06c6c3a836",
]
ONEINCH = "0x111111111117dc0aa78b770fa6a738034120c302"
NOW = datetime.now(timezone.utc)
CUTOFF = int((NOW - timedelta(days=7)).timestamp())
JST = timezone(timedelta(hours=9))

http = requests.Session()
http.headers.update({"user-agent": "aqua-top10-strategy-research/2026-08-24", "accept": "application/json"})


def log(msg: str) -> None:
    print(msg, flush=True)


def get_json(url: str, params: dict[str, Any] | None = None, tries: int = 8) -> Any:
    last: Exception | None = None
    for attempt in range(tries):
        try:
            response = http.get(url, params=params, timeout=90)
            if response.status_code == 429 or response.status_code >= 500:
                time.sleep(min(10, attempt + 1))
                continue
            response.raise_for_status()
            return response.json()
        except Exception as exc:
            last = exc
            time.sleep(min(10, attempt + 1))
    raise RuntimeError(f"GET failed: {url} params={params} error={last}")


def list_items(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        for key in ("items", "data", "campaigns", "opportunities", "rewards"):
            value = data.get(key)
            if isinstance(value, list):
                return [x for x in value if isinstance(x, dict)]
    return []


def walk(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


def token_obj(value: dict[str, Any]) -> dict[str, Any]:
    for key in ("rewardToken", "token"):
        token = value.get(key)
        if isinstance(token, dict):
            return token
    return {}


def normalize_address(value: Any) -> str:
    if isinstance(value, dict):
        for key in ("address", "hash", "addressHash", "user", "recipient"):
            found = normalize_address(value.get(key))
            if found:
                return found
        return ""
    if isinstance(value, str):
        text = value.lower().strip()
        if text.startswith("0x") and len(text) == 42:
            return text
    return ""


def amount_human(value: Any, decimals: int) -> Decimal:
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


def campaign_name(campaign: dict[str, Any]) -> str:
    opportunity = campaign.get("opportunity")
    if isinstance(opportunity, dict):
        return str(opportunity.get("name") or opportunity.get("description") or opportunity.get("id") or "")
    return str(campaign.get("opportunityName") or campaign.get("name") or "")


def campaign_metadata_by_id(campaign_id: str) -> list[dict[str, Any]]:
    data = get_json(
        f"{MERKL}/campaigns",
        {"campaignId": campaign_id, "withOpportunity": "true", "items": 100},
    )
    return [
        row
        for row in list_items(data)
        if str(row.get("campaignId") or "").lower() == campaign_id.lower()
    ]


def discover_aqua_campaigns() -> list[dict[str, Any]]:
    ids: set[str] = set()
    for anchor in ANCHORS:
        for params in (
            {"reloadChainId": "1"},
            {"chainId": "1", "reloadChainId": "1"},
            {},
        ):
            try:
                data = get_json(f"{MERKL}/users/{anchor}/rewards", params)
                for obj in walk(data):
                    cid = obj.get("campaignId") or obj.get("campaign_id")
                    if isinstance(cid, str) and cid.startswith("0x"):
                        ids.add(cid.lower())
                break
            except Exception as exc:
                log(f"MERKL_ANCHOR_RETRY|address={anchor}|params={params}|error={exc!r}")

    for symbol in ("1INCH", "USDC"):
        try:
            data = get_json(
                f"{MERKL}/campaigns",
                {"tokenSymbol": symbol, "withOpportunity": "true", "items": 1000},
            )
            for row in list_items(data):
                cid = row.get("campaignId")
                if isinstance(cid, str) and cid.startswith("0x"):
                    ids.add(cid.lower())
        except Exception as exc:
            log(f"MERKL_DISCOVERY_FAIL|symbol={symbol}|error={exc!r}")

    candidates: dict[tuple[int, str, str], dict[str, Any]] = {}
    for idx, cid in enumerate(sorted(ids), 1):
        try:
            metadata_rows = campaign_metadata_by_id(cid)
        except Exception as exc:
            log(f"CAMPAIGN_METADATA_FAIL|campaignId={cid}|error={exc!r}")
            continue

        for campaign in metadata_rows:
            token = token_obj(campaign)
            symbol = str(token.get("symbol") or campaign.get("tokenSymbol") or "").upper()
            if symbol not in {"1INCH", "USDC"}:
                continue
            start = int(campaign.get("startTimestamp") or campaign.get("start") or 0)
            end = int(campaign.get("endTimestamp") or campaign.get("end") or 0)
            name = campaign_name(campaign)
            blob = json.dumps(campaign, ensure_ascii=False).lower()
            launch_window = 1785000000 <= start <= 1785700000
            season_end = 1792500000 <= end <= 1794500000
            is_aqua = "aqua" in blob or ("1inch" in blob and launch_window)
            if not (is_aqua and launch_window and season_end):
                continue
            chain = int(
                campaign.get("distributionChainId")
                or campaign.get("chainId")
                or campaign.get("computeChainId")
                or 1
            )
            decimals = int(token.get("decimals") or (6 if symbol == "USDC" else 18))
            key = (chain, cid, symbol)
            candidates[key] = {
                "campaignId": cid,
                "dbId": campaign.get("id"),
                "name": name,
                "symbol": symbol,
                "decimals": decimals,
                "distributionChainId": chain,
                "computeChainId": campaign.get("computeChainId"),
                "start": start,
                "end": end,
            }
        if idx % 20 == 0:
            log(f"CAMPAIGN_METADATA_PROGRESS|checked={idx}|ids={len(ids)}")

    campaigns = sorted(
        candidates.values(),
        key=lambda x: (x["name"], x["symbol"], x["campaignId"]),
    )
    log(f"AQUA_CAMPAIGNS|count={len(campaigns)}")
    for campaign in campaigns:
        log(
            "AQUA_CAMPAIGN|"
            + "|".join(
                f"{k}={campaign[k]}"
                for k in (
                    "name",
                    "symbol",
                    "campaignId",
                    "distributionChainId",
                    "computeChainId",
                    "start",
                    "end",
                )
            )
        )
    if len(campaigns) < 8:
        raise RuntimeError(f"Too few Aqua campaigns discovered: {len(campaigns)}")
    return campaigns


def campaign_rewards(campaign: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    page = 0
    while page < 100:
        data = get_json(
            f"{MERKL}/rewards",
            {
                "chainId": campaign["distributionChainId"],
                "campaignId": campaign["campaignId"],
                "items": 1000,
                "page": page,
            },
        )
        current = list_items(data)
        if not current:
            break
        rows.extend(current)
        if len(current) < 1000:
            break
        page += 1
    return rows


def current_top10(campaigns: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    aggregate: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "1INCH": Decimal(0),
            "USDC": Decimal(0),
            "amount1INCH": Decimal(0),
            "pending1INCH": Decimal(0),
            "amountUSDC": Decimal(0),
            "pendingUSDC": Decimal(0),
            "categories": defaultdict(lambda: {"1INCH": Decimal(0), "USDC": Decimal(0)}),
        }
    )
    per_campaign: list[dict[str, Any]] = []

    for index, campaign in enumerate(campaigns, 1):
        rows = campaign_rewards(campaign)
        parsed = 0
        for row in rows:
            user = normalize_address(row.get("user") or row.get("address") or row.get("recipient"))
            if not user:
                continue
            amount = amount_human(
                row.get("amount") or row.get("reward") or row.get("value"),
                campaign["decimals"],
            )
            pending = amount_human(row.get("pending"), campaign["decimals"])
            total = amount + pending
            if total <= 0:
                continue
            symbol = campaign["symbol"]
            aggregate[user][symbol] += total
            aggregate[user][f"amount{symbol}"] += amount
            aggregate[user][f"pending{symbol}"] += pending
            aggregate[user]["categories"][campaign["name"]][symbol] += total
            parsed += 1
        per_campaign.append({**campaign, "users": parsed})
        log(
            f"CAMPAIGN_REWARDS|index={index}/{len(campaigns)}|"
            f"name={campaign['name']}|symbol={campaign['symbol']}|users={parsed}"
        )

    ranking = []
    for address, data in aggregate.items():
        ranking.append(
            {
                "address": address,
                "oneInch": data["1INCH"],
                "usdc": data["USDC"],
                "amount1INCH": data["amount1INCH"],
                "pending1INCH": data["pending1INCH"],
                "amountUSDC": data["amountUSDC"],
                "pendingUSDC": data["pendingUSDC"],
                "categories": data["categories"],
            }
        )
    ranking.sort(key=lambda x: (x["oneInch"], x["usdc"]), reverse=True)
    for rank, row in enumerate(ranking, 1):
        row["rank"] = rank

    top10 = ranking[:10]
    log(f"GLOBAL_RANKED_USERS|count={len(ranking)}")
    for row in top10:
        categories = sorted(
            row["categories"].items(),
            key=lambda kv: kv[1]["1INCH"],
            reverse=True,
        )
        log(
            f"TOP10|rank={row['rank']}|address={row['address']}|"
            f"oneInch={row['oneInch']}|usdc={row['usdc']}|"
            f"amount1INCH={row['amount1INCH']}|pending1INCH={row['pending1INCH']}|"
            f"categories="
            + ";".join(
                f"{name}:1INCH={value['1INCH']},USDC={value['USDC']}"
                for name, value in categories
                if value["1INCH"] or value["USDC"]
            )
        )

    return top10, {"ranking": ranking, "campaigns": per_campaign}


class McpClient:
    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update(
            {
                "accept": "application/json, text/event-stream",
                "content-type": "application/json",
                "user-agent": "aqua-top10-strategy-research/2026-08-24",
            }
        )
        self.session_id: str | None = None
        self.request_id = 0
        self.initialize()

    @staticmethod
    def parse_sse(body: str, expected_id: int) -> dict[str, Any]:
        normalized = body.replace("\r\n", "\n").strip()
        messages: list[dict[str, Any]] = []
        if normalized.startswith("data:") or "event:" in normalized[:50]:
            for block in normalized.split("\n\n"):
                data_lines = [
                    line[5:].lstrip()
                    for line in block.split("\n")
                    if line.startswith("data:")
                ]
                if not data_lines:
                    continue
                payload = "\n".join(data_lines)
                if payload == "[DONE]":
                    continue
                messages.append(json.loads(payload))
        else:
            parsed = json.loads(normalized)
            messages = parsed if isinstance(parsed, list) else [parsed]
        for message in messages:
            if str(message.get("id")) == str(expected_id):
                return message
        raise RuntimeError(f"Missing MCP response id={expected_id}; messages={len(messages)}")

    def initialize(self) -> None:
        self.session_id = None
        self.request(
            "initialize",
            {
                "protocolVersion": MCP_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "aqua-top10-strategy-research", "version": "1.0"},
            },
            retry_reinit=False,
        )
        self.notify("notifications/initialized", {})

    def post(self, payload: dict[str, Any], expected_id: int | None) -> Any:
        headers = {"MCP-Protocol-Version": MCP_VERSION}
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        response = self.session.post(MCP, json=payload, headers=headers, timeout=120)
        if response.status_code == 429 or response.status_code >= 500:
            raise RuntimeError(f"MCP HTTP {response.status_code}: {response.text[:300]}")
        response.raise_for_status()
        if response.headers.get("mcp-session-id"):
            self.session_id = response.headers["mcp-session-id"]
        if expected_id is None:
            return None
        envelope = self.parse_sse(response.text, expected_id)
        if envelope.get("error"):
            raise RuntimeError(envelope["error"])
        return envelope.get("result")

    def request(
        self,
        method: str,
        params: dict[str, Any],
        retry_reinit: bool = True,
    ) -> Any:
        last: Exception | None = None
        for attempt in range(8):
            self.request_id += 1
            request_id = self.request_id
            payload = {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": method,
                "params": params,
            }
            try:
                return self.post(payload, request_id)
            except Exception as exc:
                last = exc
                log(
                    f"MCP_RETRY|method={method}|attempt={attempt + 1}|"
                    f"error={exc!r}"
                )
                if retry_reinit and method != "initialize":
                    try:
                        self.initialize()
                    except Exception as init_exc:
                        log(f"MCP_REINIT_FAIL|error={init_exc!r}")
                time.sleep(min(12, attempt + 1))
        raise RuntimeError(f"MCP request failed: method={method} error={last}")

    def notify(self, method: str, params: dict[str, Any]) -> None:
        payload = {"jsonrpc": "2.0", "method": method, "params": params}
        self.post(payload, None)

    def aqua(self, arguments: dict[str, Any]) -> Any:
        result = self.request(
            "tools/call",
            {"name": "aqua", "arguments": arguments},
        )
        if isinstance(result, dict) and result.get("isError"):
            raise RuntimeError(result)
        if isinstance(result, dict) and result.get("structuredContent") is not None:
            return result["structuredContent"]
        parsed_values = []
        for item in (result.get("content") if isinstance(result, dict) else []) or []:
            text = item.get("text") if isinstance(item, dict) else None
            if isinstance(text, str):
                try:
                    parsed_values.append(json.loads(text))
                except json.JSONDecodeError:
                    continue
        if len(parsed_values) == 1:
            return parsed_values[0]
        return parsed_values or result


def volume7d(strategy: dict[str, Any]) -> float:
    try:
        return float(
            strategy.get("performance", {})
            .get("volume", {})
            .get("last7d", {})
            .get("usd")
            or 0
        )
    except Exception:
        return 0.0


def fees7d(strategy: dict[str, Any]) -> float:
    try:
        return float(
            strategy.get("performance", {})
            .get("fees", {})
            .get("last7d", {})
            .get("usd")
            or 0
        )
    except Exception:
        return 0.0


def fetch_strategies(mcp: McpClient, address: str, status: str) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    cursor: str | None = None
    seen: set[str] = set()
    for page in range(100):
        arguments: dict[str, Any] = {
            "action": "list_maker_strategies",
            "address": address,
            "status": [status],
            "limit": 25,
        }
        if cursor:
            arguments["cursor"] = cursor
        data = mcp.aqua(arguments)
        items = data.get("items") if isinstance(data, dict) else []
        if not items:
            break
        output.extend(items)
        cursor = data.get("nextCursor") if isinstance(data, dict) else None
        log(
            f"STRATEGY_PAGE|address={address}|status={status}|"
            f"page={page + 1}|items={len(items)}|total={len(output)}"
        )
        if not cursor or cursor in seen:
            break
        seen.add(cursor)
        if status == "closed":
            if all(
                int(item.get("openedAt") or 0) < CUTOFF
                and int(item.get("closedAt") or 0) < CUTOFF
                and volume7d(item) == 0
                for item in items
            ):
                break
    return output


def decode_price_range(strategy: dict[str, Any]) -> dict[str, Any] | None:
    strategy_bytes = strategy.get("strategyBytes")
    tokens = strategy.get("tokens") or []
    if not isinstance(strategy_bytes, str) or len(tokens) < 2:
        return None
    raw = bytes.fromhex(strategy_bytes.removeprefix("0x"))
    if len(raw) < 160:
        return None
    program_length = int.from_bytes(raw[128:160], "big")
    program = raw[160 : 160 + program_length]
    if len(program) < 114:
        return None

    sqrt_a = int.from_bytes(program[50:82], "big")
    sqrt_b = int.from_bytes(program[82:114], "big")
    if sqrt_a <= 0 or sqrt_b <= 0:
        return None
    sqrt_lo, sqrt_hi = min(sqrt_a, sqrt_b), max(sqrt_a, sqrt_b)
    raw_lo = (Decimal(sqrt_lo) / Decimal(10**18)) ** 2
    raw_hi = (Decimal(sqrt_hi) / Decimal(10**18)) ** 2

    t0, t1 = tokens[0], tokens[1]
    address0 = str(t0.get("address") or "").lower()
    address1 = str(t1.get("address") or "").lower()
    meta0 = t0.get("meta") or {}
    meta1 = t1.get("meta") or {}
    decimals0 = int(meta0.get("decimals") or 18)
    decimals1 = int(meta1.get("decimals") or 18)
    symbol0 = str(meta0.get("symbol") or address0)
    symbol1 = str(meta1.get("symbol") or address1)

    if not (address0.startswith("0x") and address1.startswith("0x")):
        return None

    if int(address0, 16) < int(address1, 16):
        price_min = raw_lo * (Decimal(10) ** (decimals0 - decimals1))
        price_max = raw_hi * (Decimal(10) ** (decimals0 - decimals1))
    else:
        gt_min = raw_lo * (Decimal(10) ** (decimals1 - decimals0))
        gt_max = raw_hi * (Decimal(10) ** (decimals1 - decimals0))
        price_min = Decimal(1) / gt_max
        price_max = Decimal(1) / gt_min

    if address0 == ONEINCH:
        base_symbol, quote_symbol = symbol0, symbol1
        normalized_min, normalized_max = price_min, price_max
    elif address1 == ONEINCH:
        base_symbol, quote_symbol = symbol1, symbol0
        normalized_min = Decimal(1) / price_max
        normalized_max = Decimal(1) / price_min
    else:
        base_symbol, quote_symbol = symbol0, symbol1
        normalized_min, normalized_max = price_min, price_max

    midpoint = (normalized_min + normalized_max) / 2
    width_pct = (
        (normalized_max - normalized_min) / midpoint * Decimal(100)
        if midpoint
        else None
    )
    return {
        "pair": f"{base_symbol}/{quote_symbol}",
        "baseSymbol": base_symbol,
        "quoteSymbol": quote_symbol,
        "min": str(normalized_min),
        "max": str(normalized_max),
        "mid": str(midpoint),
        "widthPct": float(width_pct) if width_pct is not None else None,
        "sqrtMin": str(sqrt_lo),
        "sqrtMax": str(sqrt_hi),
    }


def quantile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * p
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def mode_value(values: list[Any]) -> Any:
    if not values:
        return None
    return Counter(str(value) for value in values).most_common(1)[0][0]


def strategy_analysis(
    mcp: McpClient,
    top10: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    reports = []
    for ranking in top10:
        address = ranking["address"]
        log(f"ADDRESS_START|rank={ranking['rank']}|address={address}")
        try:
            raw_strategies = fetch_strategies(mcp, address, "open") + fetch_strategies(
                mcp, address, "closed"
            )
        except Exception as exc:
            log(f"ADDRESS_FAIL|rank={ranking['rank']}|address={address}|error={exc!r}")
            reports.append(
                {
                    "rank": ranking["rank"],
                    "address": address,
                    "error": repr(exc),
                    "reward1INCH": str(ranking["oneInch"]),
                    "rewardUSDC": str(ranking["usdc"]),
                }
            )
            continue

        unique: dict[tuple[Any, Any, Any], dict[str, Any]] = {}
        for strategy in raw_strategies:
            key = (
                strategy.get("chainId"),
                strategy.get("app"),
                strategy.get("strategyHash"),
            )
            unique[key] = strategy

        rows = []
        for strategy in unique.values():
            opened_at = int(strategy.get("openedAt") or 0)
            closed_at = int(strategy.get("closedAt") or 0)
            is_open = not bool(strategy.get("closedAt"))
            rolling_volume = volume7d(strategy)
            if not (
                is_open
                or opened_at >= CUTOFF
                or closed_at >= CUTOFF
                or rolling_volume > 0
            ):
                continue
            try:
                price_range = decode_price_range(strategy) or {}
            except Exception as exc:
                log(
                    f"DECODE_FAIL|address={address}|hash={strategy.get('strategyHash')}|"
                    f"error={exc!r}"
                )
                price_range = {}
            tokens = strategy.get("tokens") or []
            fallback_pair = "/".join(
                str((token.get("meta") or {}).get("symbol") or "?")
                for token in tokens[:2]
            )
            classification = strategy.get("classification") or {}
            rows.append(
                {
                    "chainId": int(strategy.get("chainId") or 0),
                    "app": strategy.get("app"),
                    "strategyHash": strategy.get("strategyHash"),
                    "openedAt": opened_at,
                    "closedAt": strategy.get("closedAt"),
                    "status": "open" if is_open else "closed",
                    "pair": price_range.get("pair") or fallback_pair,
                    "quoteSymbol": price_range.get("quoteSymbol"),
                    "rangeMin": price_range.get("min"),
                    "rangeMax": price_range.get("max"),
                    "midPrice": price_range.get("mid"),
                    "widthPct": price_range.get("widthPct"),
                    "feePercent": classification.get("feePercent"),
                    "type": classification.get("type"),
                    "state": classification.get("state"),
                    "volume7dUsd": rolling_volume,
                    "fees7dUsd": fees7d(strategy),
                    "initialLiquidityUsd": sum(
                        float((token.get("initialBalance") or {}).get("usd") or 0)
                        for token in tokens
                    ),
                    "currentLiquidityUsd": sum(
                        float((token.get("currentBalance") or {}).get("usd") or 0)
                        for token in tokens
                    ),
                }
            )

        rows.sort(key=lambda x: x["openedAt"], reverse=True)
        grouped: dict[tuple[int, str], list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            grouped[(row["chainId"], row["pair"])].append(row)

        pairs = []
        for (chain_id, pair), values in grouped.items():
            widths = [v["widthPct"] for v in values if v["widthPct"] is not None]
            active_values = [v for v in values if v["status"] == "open"]
            latest = max(values, key=lambda x: x["openedAt"])
            volume = sum(v["volume7dUsd"] for v in values)
            fees = sum(v["fees7dUsd"] for v in values)
            weighted_volume = sum(
                v["volume7dUsd"] for v in values if v["widthPct"] is not None
            )
            volume_weighted_width = (
                sum(v["widthPct"] * v["volume7dUsd"] for v in values if v["widthPct"] is not None)
                / weighted_volume
                if weighted_volume > 0
                else None
            )
            pairs.append(
                {
                    "chainId": chain_id,
                    "pair": pair,
                    "strategies": len(values),
                    "opened7d": sum(v["openedAt"] >= CUTOFF for v in values),
                    "closed7d": sum(
                        bool(v["closedAt"]) and int(v["closedAt"]) >= CUTOFF
                        for v in values
                    ),
                    "active": len(active_values),
                    "volume7dUsd": volume,
                    "fees7dUsd": fees,
                    "medianWidthPct": statistics.median(widths) if widths else None,
                    "p25WidthPct": quantile(widths, 0.25),
                    "p75WidthPct": quantile(widths, 0.75),
                    "minWidthPct": min(widths) if widths else None,
                    "maxWidthPct": max(widths) if widths else None,
                    "volumeWeightedWidthPct": volume_weighted_width,
                    "feeModePct": mode_value([v["feePercent"] for v in values]),
                    "feeDistribution": dict(
                        Counter(str(v["feePercent"]) for v in values)
                    ),
                    "latest": latest,
                }
            )
        pairs.sort(key=lambda x: (x["volume7dUsd"], x["strategies"]), reverse=True)

        widths = [row["widthPct"] for row in rows if row["widthPct"] is not None]
        volume_widths = [
            row for row in rows if row["widthPct"] is not None and row["volume7dUsd"] > 0
        ]
        chain_mix = defaultdict(
            lambda: {
                "strategies": 0,
                "active": 0,
                "opened7d": 0,
                "closed7d": 0,
                "volume7dUsd": 0.0,
            }
        )
        for row in rows:
            chain = chain_mix[str(row["chainId"])]
            chain["strategies"] += 1
            chain["active"] += row["status"] == "open"
            chain["opened7d"] += row["openedAt"] >= CUTOFF
            chain["closed7d"] += bool(row["closedAt"]) and int(row["closedAt"]) >= CUTOFF
            chain["volume7dUsd"] += row["volume7dUsd"]

        report = {
            "rank": ranking["rank"],
            "address": address,
            "reward1INCH": str(ranking["oneInch"]),
            "rewardUSDC": str(ranking["usdc"]),
            "rewardAmount1INCH": str(ranking["amount1INCH"]),
            "rewardPending1INCH": str(ranking["pending1INCH"]),
            "strategies": len(rows),
            "active": sum(row["status"] == "open" for row in rows),
            "opened7d": sum(row["openedAt"] >= CUTOFF for row in rows),
            "closed7d": sum(
                bool(row["closedAt"]) and int(row["closedAt"]) >= CUTOFF
                for row in rows
            ),
            "volume7dUsd": sum(row["volume7dUsd"] for row in rows),
            "fees7dUsd": sum(row["fees7dUsd"] for row in rows),
            "width": {
                "min": min(widths) if widths else None,
                "p25": quantile(widths, 0.25),
                "median": statistics.median(widths) if widths else None,
                "p75": quantile(widths, 0.75),
                "max": max(widths) if widths else None,
                "volumeWeighted": (
                    sum(row["widthPct"] * row["volume7dUsd"] for row in volume_widths)
                    / sum(row["volume7dUsd"] for row in volume_widths)
                    if volume_widths and sum(row["volume7dUsd"] for row in volume_widths) > 0
                    else None
                ),
            },
            "feeDistribution": dict(Counter(str(row["feePercent"]) for row in rows)),
            "chainMix": dict(chain_mix),
            "pairs": pairs,
            "rows": rows,
        }
        reports.append(report)
        top_pairs = pairs[:10]
        log(
            f"SUMMARY|rank={report['rank']}|address={address}|"
            f"strategies={report['strategies']}|active={report['active']}|"
            f"opened7d={report['opened7d']}|closed7d={report['closed7d']}|"
            f"volume7dUsd={report['volume7dUsd']:.2f}|"
            f"medianWidthPct={report['width']['median']}|"
            f"volumeWeightedWidthPct={report['width']['volumeWeighted']}|"
            f"pairs="
            + ",".join(
                f"{p['chainId']}:{p['pair']}:n{p['strategies']}:a{p['active']}:"
                f"v{p['volume7dUsd']:.0f}:w{(p['medianWidthPct'] or 0):.6f}:"
                f"vw{(p['volumeWeightedWidthPct'] or 0):.6f}:fee{p['feeModePct']}"
                for p in top_pairs
            )
        )
    return reports


def decimal_default(value: Any):
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError(type(value).__name__)


def fmt_money(value: float) -> str:
    return f"${value:,.2f}"


def fmt_pct(value: float | None) -> str:
    return "—" if value is None else f"{value:.4f}%"


def jst_time(timestamp: int | None) -> str:
    if not timestamp:
        return "—"
    return datetime.fromtimestamp(int(timestamp), timezone.utc).astimezone(JST).strftime(
        "%Y-%m-%d %H:%M:%S JST"
    )


def write_markdown(
    top10: list[dict[str, Any]],
    reports: list[dict[str, Any]],
) -> None:
    lines = [
        "# Aqua Season 1 当前前十地址：近 7 日策略",
        "",
        f"- 数据快照：{NOW.astimezone(JST).strftime('%Y-%m-%d %H:%M:%S JST')}",
        f"- 滚动窗口起点：{datetime.fromtimestamp(CUTOFF, timezone.utc).astimezone(JST).strftime('%Y-%m-%d %H:%M:%S JST')}",
        "- 排名：Merkl Aqua Season 1 所有已发现 1INCH/USDC campaigns，按 `amount + pending` 跨类别、跨链、按地址去重汇总。",
        "- 策略：1inch 官方 MCP `aqua.list_maker_strategies`；价格上下限由策略字节码直接解码。",
        "",
        "## 当前排名与近 7 日概览",
        "",
        "| 排名 | 地址 | 累计1INCH | 累计USDC | 7日新开/关闭/现开 | 7日成交量 | 区间中位数 | 成交量加权宽度 |",
        "|---:|---|---:|---:|---:|---:|---:|---:|",
    ]
    by_address = {report["address"]: report for report in reports}
    for ranking in top10:
        report = by_address.get(ranking["address"], {})
        lines.append(
            f"| {ranking['rank']} | `{ranking['address']}` | "
            f"{Decimal(ranking['oneInch']):,.6f} | {Decimal(ranking['usdc']):,.6f} | "
            f"{report.get('opened7d', '—')}/{report.get('closed7d', '—')}/{report.get('active', '—')} | "
            f"{fmt_money(report.get('volume7dUsd', 0)) if report else '—'} | "
            f"{fmt_pct((report.get('width') or {}).get('median')) if report else '—'} | "
            f"{fmt_pct((report.get('width') or {}).get('volumeWeighted')) if report else '—'} |"
        )

    for report in reports:
        if report.get("error"):
            continue
        lines += [
            "",
            f"## #{report['rank']} `{report['address']}`",
            "",
            f"- 累计奖励：{Decimal(report['reward1INCH']):,.6f} 1INCH + {Decimal(report['rewardUSDC']):,.6f} USDC",
            f"- 近 7 日：新开 {report['opened7d']}、关闭 {report['closed7d']}、当前开放 {report['active']}；成交量 {fmt_money(report['volume7dUsd'])}",
            f"- 区间总宽度：中位数 {fmt_pct(report['width']['median'])}；成交量加权 {fmt_pct(report['width']['volumeWeighted'])}",
            f"- 链分布：`{json.dumps(report['chainMix'], ensure_ascii=False)}`",
            "",
            "| 链 | 币对 | 策略数 | 新开/关闭/现开 | 7日成交量 | 中位宽度 | 加权宽度 | 常用费率 | 最新区间 |",
            "|---:|---|---:|---:|---:|---:|---:|---:|---|",
        ]
        for pair in report["pairs"][:12]:
            latest = pair["latest"]
            latest_range = (
                f"{latest['rangeMin']} – {latest['rangeMax']} {latest['quoteSymbol']}/1INCH"
                if latest.get("rangeMin") and latest.get("rangeMax")
                else "—"
            )
            lines.append(
                f"| {pair['chainId']} | {pair['pair']} | {pair['strategies']} | "
                f"{pair['opened7d']}/{pair['closed7d']}/{pair['active']} | "
                f"{fmt_money(pair['volume7dUsd'])} | {fmt_pct(pair['medianWidthPct'])} | "
                f"{fmt_pct(pair['volumeWeightedWidthPct'])} | {pair['feeModePct']}% | "
                f"{latest_range}（{jst_time(latest['openedAt'])}） |"
            )

    Path("aqua_top10_current_strategies.md").write_text(
        "\n".join(lines), encoding="utf-8"
    )


def main() -> None:
    campaigns = discover_aqua_campaigns()
    top10, ranking_data = current_top10(campaigns)
    mcp = McpClient()
    strategy_reports = strategy_analysis(mcp, top10)

    result = {
        "snapshotUtc": NOW.isoformat(),
        "snapshotJst": NOW.astimezone(JST).isoformat(),
        "cutoffUtc": datetime.fromtimestamp(CUTOFF, timezone.utc).isoformat(),
        "cutoffJst": datetime.fromtimestamp(CUTOFF, timezone.utc).astimezone(JST).isoformat(),
        "campaigns": ranking_data["campaigns"],
        "top10": top10,
        "strategyReports": strategy_reports,
    }
    Path("aqua_top10_current_strategies.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, default=decimal_default),
        encoding="utf-8",
    )
    write_markdown(top10, strategy_reports)
    log("OUTPUT|json=aqua_top10_current_strategies.json|md=aqua_top10_current_strategies.md")


if __name__ == "__main__":
    main()
