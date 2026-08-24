# Aqua Season 1 current top-10 strategy summary

Snapshot: 2026-08-24T13:36:13.300499+09:00. Rolling window starts: 2026-08-17T13:36:13+09:00.
Ranking is aggregated across the 16 verified Season 1 root campaigns (8 categories × 1INCH/USDC), by address, using amount + pending. Strategy data is from 1inch Aqua MCP list_maker_strategies; ranges are decoded from strategyBytes.

## Current top 10

|Rank|Address|1INCH|USDC|Opened/Closed/Active 7d|Volume 7d|Median width|Volume-weighted width|
|---:|---|---:|---:|---:|---:|---:|---:|
|1|`0xe22259232b3cf5c74104cf2ded7f878f0201b198`|352,263.187015|35,226.318694|0/21/0|$72,332.12|10.66502057728365|12.288882184416495|
|2|`0x3bb5c8a00190da68059f0f66c24794584eb10d07`|257,621.222961|25,762.122290|360/374/0|$16,668,792.93|0.3621001811967002|0.8246998618624382|
|3|`0xe01ecff2f6c4f2416e83e6861e8abf79b1c95950`|111,468.319464|11,146.831935|307/316/14|$1,739,688.96|0.30733763723808555|0.5671778081153016|
|4|`0x5510accff071694262fcb4dc317bf65a02aaf4f8`|102,150.829249|10,215.082918|134/146/0|$3,740,908.97|0.24446113833377597|0.8806188882705231|
|5|`0x50e01433711f0cde93d09856405f64a579fa5244`|59,864.634139|5,986.463411|0/0/0|$0.00|—|—|
|6|`0xcb8804d2df7173da7634a6e303149429590105da`|55,604.339130|5,560.433904|2312/2310/12|$4,272,168.65|0.3749999999999975|0.6378422136665404|
|7|`0x8f61ee081111e6bce0301a4bd5567d02322c8f9f`|55,323.642567|5,532.364254|232/229/3|$3,547,552.05|0.04818397917366629|0.09883678983324402|
|8|`0x5e9d829566e4ae453cfa8d29d62b1af483a0b534`|54,220.022502|5,422.002246|355/356/3|$6,893,151.17|0.2866086821771003|2.121669611529691|
|9|`0x3e716f13cd4ec7bfc39917f3416a94bf5eec11b5`|46,299.077080|4,629.907705|15/17/1|$659,268.93|0.21515149044365242|0.5376669641933292|
|10|`0xa0996c6e3d6525b80873fa5ef6b39f7468fb90f4`|43,148.815458|4,314.881542|0/0/0|$0.00|—|—|

## Profiles

### #1 `0xe22259232b3cf5c74104cf2ded7f878f0201b198`

Wide-range passive inventory strategy. No new positions; all 21 observed strategies closed by Aug 20. Volume concentrated in WETH, USDT, ONDO and wstETH. Core widths are about 3.7%-18.3%, long-tail AAVE 29.4%; fee settings 0.01%-1%. This address is a cumulative-reward leader but is currently inactive.

### #2 `0x3bb5c8a00190da68059f0f66c24794584eb10d07`

High-frequency narrow-range market maker. 360 opens and 374 closes, $16.67m seven-day volume, mostly USDT (49.8%), WETH (27.9%) and USDC (10.7%). Core median widths: USDT 0.2839%, WETH 0.4267%, USDC 0.3630%, WBTC 0.3681%, DAI 0.3318%; fee mode 0.001%. No open positions at the snapshot, but the latest batch traded until Aug 24 02:44 JST.

### #3 `0xe01ecff2f6c4f2416e83e6861e8abf79b1c95950`

E01e uses a multi-chain barbell. Ethereum core is high-frequency/narrow: WETH 0.0992%, USDT 0.0574%, syrupUSDC 0.1321%, UNI 0.1918%, with 95.7% of seven-day volume on Ethereum. Robinhood Chain (4663) and BNB (56) are wider RWA/VIRTUAL satellites, often 1.7%-20%+ and fees 0.05%-1%. Fourteen positions were open, mainly Robinhood/BNB; Ethereum core positions were closed at snapshot.

### #4 `0x5510accff071694262fcb4dc317bf65a02aaf4f8`

Stablecoin-heavy narrow maker. $3.74m volume: USDT 36.4%, USDC 35.4%, WETH 20.5%. Median widths: USDT 0.1808%, USDC 0.2059%, WETH 0.25%, WBTC 0.06%; UNI 2%, ONDO 6.4%, AAVE 4.5%. Fee mode 0.001%. All positions closed by Aug 23 14:51 JST, so currently paused.

### #5 `0x50e01433711f0cde93d09856405f64a579fa5244`

Historical winner but no current strategy: no opens, closes, active positions or seven-day volume. Reward total unchanged since Aug 12.

### #6 `0xcb8804d2df7173da7634a6e303149429590105da`

Industrial template/grid re-pricer. 2,312 opens and 2,310 closes (~330 opens/day), $4.27m volume across Ethereum, BNB and Robinhood. Core templates cluster at ~0.35% for USDC/WETH/DAI/WBTC/USDT, 0.45% wstETH; PAXG ~1%, ONDO ~3%, VIRTUAL ~5.4%, BNB CRCLon ~2%. Fees: 0.001% core, 0.005% Robinhood, 0.05% BNB. Twelve positions open.

### #7 `0x8f61ee081111e6bce0301a4bd5567d02322c8f9f`

Micro-range stable/ETH maker. 232 opens, 229 closes, $3.55m volume. Median width 0.0482%, weighted 0.0988%. USDC 0.0410%, USDT 0.0370%, WETH 0.1208%, WBTC 0.1809%, stETH 0.1054%; fee mode 0.001%. Core 1INCH pairs were closed; three active positions were USDC/USDT inventory-rebalancing bands.

### #8 `0x5e9d829566e4ae453cfa8d29d62b1af483a0b534`

High-volume volatile-asset strategy. 355 opens/356 closes, $6.89m volume. WETH 39.3%, WBTC 29.8%, USDT 17.4%, UNI 12.0%. Wider volatile bands: WETH 1.2407%, WBTC 0.5103%, UNI 4.9706%; tighter USDT 0.1187% and USDC 0.0396%. Three positions open: two WETH and one USDT. This is not pure micro-range HFT; it combines reward volume with wider inventory/risk bands.

### #9 `0x3e716f13cd4ec7bfc39917f3416a94bf5eec11b5`

Focused, lower-frequency stablecoin maker. 15 opens/17 closes, $659k volume; USDT 71.1% and USDC 24.8%. Median widths: USDT 0.1313%, USDC 0.4779%; minor AAVE 2.88% and WLFI 0.067%. One USDT position open.

### #10 `0xa0996c6e3d6525b80873fa5ef6b39f7468fb90f4`

Historical/inactive address: no open, close, active strategy or seven-day volume. Reward total unchanged since Aug 12.

## Ranking changes since Aug 12

New entrants: cb8804 (#6), 8f61ee (#7), 5e9d82 (#8). Dropped out: fff80d, 8b02c8, 3ca301. The top three remained e222, 3bb5, E01e. 5510 moved from #5 to #4; 50e fell from #4 to #5; 3e71 fell from #7 to #9; a099 fell from #6 to #10.