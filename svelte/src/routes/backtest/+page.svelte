<script>
	import { fetchBacktestRuns, startBacktest, fetchBacktestProgress, stopBacktest } from '$lib/api';

	let runs = $state([]);
	let loading = $state(true);
	let error = $state('');

	// Form
	let symbol = $state('XAUUSD');
	let periodType = $state('months'); // 'days' | 'months'
	let monthsBack = $state(3);
	let daysBack = $state(10);
	let lotSize = $state(0.01);
	let initialCapital = $state(10000);

	// Running state
	let runningId = $state(null);
	let progress = $state(null);
	let pollingInterval = $state(null);
	let stopping = $state(false);

	// Detail view
	let selectedRun = $state(null);
	let showDetail = $state(false);

	function selectRun(run) {
		selectedRun = run;
		showDetail = true;
	}

	function closeDetail() {
		showDetail = false;
		selectedRun = null;
	}

	function drawEquityCurve(equityCurve, initialBalance) {
		if (!equityCurve || equityCurve.length === 0) return null;

		// Downsample: 1 point per 50 candles, always include first & last
		const sampled = [];
		const step = Math.max(1, Math.floor(equityCurve.length / 120));
		for (let i = 0; i < equityCurve.length; i += step) {
			sampled.push(equityCurve[i]);
		}
		if (sampled[sampled.length - 1] !== equityCurve[equityCurve.length - 1]) {
			sampled.push(equityCurve[equityCurve.length - 1]);
		}

		const equities = sampled.map(p => p.equity);
		const minEquity = Math.min(...equities) * 0.95;
		const maxEquity = Math.max(...equities) * 1.05;
		const range = maxEquity - minEquity || 1;

		const points = sampled.map((p, i) => {
			const x = (i / (sampled.length - 1 || 1)) * 580 + 10;
			const y = 190 - ((p.equity - minEquity) / range) * 180;
			return `${x.toFixed(1)},${y.toFixed(1)}`;
		}).join(' ');

		const finalEquity = equityCurve[equityCurve.length - 1]?.equity ?? initialBalance;

		// Y position of initial balance on the same scale as equity points
		const initialBalanceY = 190 - ((initialBalance - minEquity) / range) * 180;

		return { points, minEquity, maxEquity, initialBalance, finalEquity, initialBalanceY };
	}

	async function loadRuns() {
		try {
			runs = await fetchBacktestRuns();
		} catch (e) {
			error = e.message;
		} finally {
			loading = false;
		}
	}

	async function runBacktest() {
		try {
			const params = {
				symbol,
				timeframe: 'M15',
				months_back: periodType === 'months' ? monthsBack : null,
				days_back: periodType === 'days' ? daysBack : null,
				lot_size: lotSize,
				initial_capital: initialCapital
			};
			const { run_id } = await startBacktest(params);
			runningId = run_id;
			// Start polling
			pollingInterval = setInterval(async () => {
				try {
					progress = await fetchBacktestProgress(run_id);
					if (progress.status === 'completed' || progress.status === 'error' || progress.status === 'cancelled') {
						clearInterval(pollingInterval);
						pollingInterval = null;
						runningId = null;
						stopping = false;
						loadRuns();
					}
				} catch (e) { /* ignore */ }
			}, 3000);
		} catch (e) {
			alert('Gagal start backtest: ' + e.message);
		}
	}

	async function cancelBacktest() {
		if (!runningId) return;
		stopping = true;
		try {
			await stopBacktest(runningId);
		} catch (e) {
			alert('Gagal stop backtest: ' + e.message);
			stopping = false;
		}
	}

	$effect(() => { loadRuns(); });

	function formatCurrency(val) {
		if (val == null) return '$0.00';
		return '$' + Number(val).toLocaleString('en-US', { minimumFractionDigits: 2 });
	}

	function formatDateTime(iso) {
		if (!iso) return '—';
		return new Date(iso).toLocaleString('id-ID', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
	}
</script>

<h1 class="text-2xl font-bold mb-6">Backtest</h1>

<!-- Run Backtest Form -->
<div class="bg-gray-900 border border-gray-800 rounded-xl p-6 mb-8">
	<h2 class="text-lg font-semibold mb-4">Run New Backtest</h2>
	<div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-4">
		<div>
			<label class="text-sm text-gray-400 block mb-1">Symbol</label>
			<input type="text" bind:value={symbol} class="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm" />
		</div>
		<div>
			<label class="text-sm text-gray-400 block mb-1">Period</label>
			<div class="flex gap-2 mb-2">
				<button
					onclick={() => periodType = 'days'}
					class="px-3 py-1 rounded text-xs {periodType === 'days' ? 'bg-emerald-600 text-white' : 'bg-gray-800 text-gray-400'}"
				>Days</button>
				<button
					onclick={() => periodType = 'months'}
					class="px-3 py-1 rounded text-xs {periodType === 'months' ? 'bg-emerald-600 text-white' : 'bg-gray-800 text-gray-400'}"
				>Months</button>
			</div>
			{#if periodType === 'days'}
				<select bind:value={daysBack} class="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm">
					<option value={10}>10 Days</option>
					<option value={20}>20 Days</option>
					<option value={30}>30 Days</option>
					<option value={60}>60 Days</option>
					<option value={90}>90 Days</option>
					<option value={180}>180 Days</option>
				</select>
			{:else}
				<input type="range" min="1" max="6" bind:value={monthsBack} class="w-full" />
				<span class="text-sm text-gray-500">{monthsBack} months</span>
			{/if}
		</div>
		<div>
			<label class="text-sm text-gray-400 block mb-1">Lot Size</label>
			<input type="number" step="0.01" min="0.01" bind:value={lotSize} class="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm" />
		</div>
		<div>
			<label class="text-sm text-gray-400 block mb-1">Initial Capital (USD)</label>
			<input type="number" step="100" min="100" bind:value={initialCapital} class="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm" />
		</div>
		<div class="flex items-end gap-2">
			<button
				onclick={runBacktest}
				disabled={runningId !== null}
				class="flex-1 px-4 py-2 bg-emerald-600 hover:bg-emerald-500 disabled:bg-gray-700 disabled:text-gray-500 rounded-lg text-sm font-medium transition-colors"
			>
				{runningId ? 'Running...' : '▶ Run Backtest'}
			</button>
			{#if runningId && !stopping}
				<button
					onclick={cancelBacktest}
					class="px-4 py-2 bg-red-600 hover:bg-red-500 rounded-lg text-sm font-medium transition-colors"
				>
					⏹ Stop
				</button>
			{:else if stopping}
				<button disabled class="px-4 py-2 bg-red-900/50 text-red-300 rounded-lg text-sm">
					Stopping...
				</button>
			{/if}
		</div>
	</div>

	<!-- Progress -->
	{#if runningId && progress}
		<div class="mt-4">
			<div class="flex justify-between text-sm mb-1">
				<span class="text-gray-400">Progress: {progress.status}</span>
				<span class="text-gray-500">{progress.progress_pct}%</span>
			</div>
			<div class="w-full bg-gray-800 rounded-full h-2">
				<div class="bg-emerald-500 h-2 rounded-full transition-all" style="width: {progress.progress_pct}%"></div>
			</div>
			<div class="flex gap-4 mt-2 text-xs text-gray-500">
				<span>Trades: {progress.trades_found}</span>
				<span>Candle: {progress.current_candle}</span>
			</div>
		</div>
	{/if}
</div>

<!-- Past Runs -->
<h2 class="text-lg font-semibold mb-4">Past Runs</h2>
{#if loading}
	<p class="text-gray-500">Loading...</p>
{:else if runs.length === 0}
	<p class="text-gray-500">No backtest runs yet</p>
{:else}
	<div class="space-y-4">
		{#each runs as run}
			<div class="bg-gray-900 border border-gray-800 rounded-xl p-5">
				<div class="flex items-center justify-between mb-3">
					<div>
						<span class="text-sm font-medium">{run.symbol} · {run.period || (run.months_back ? run.months_back + 'mo' : run.days_back ? run.days_back + 'd' : '?')} · {run.lot_size} lot · {formatCurrency(run.initial_capital || 10000)} capital</span>
						<span class="ml-3 px-2 py-0.5 rounded text-xs {run.status === 'completed' ? 'bg-emerald-900/30 text-emerald-300' : run.status === 'error' ? 'bg-red-900/30 text-red-300' : 'bg-blue-900/30 text-blue-300'}">
							{run.status}
						</span>
					</div>
					<div class="flex items-center gap-3">
						<button
							onclick={() => selectRun(run)}
							class="text-xs text-blue-400 hover:text-blue-300 underline"
						>
							📊 View Detail
						</button>
						<span class="text-xs text-gray-500">{formatDateTime(run.created_at)}</span>
					</div>
				</div>

				{#if run.stats}
					<div class="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-7 gap-3 text-sm">
						<div class="bg-gray-800 rounded-lg p-3 text-center">
							<div class="text-xs text-gray-500">Win Rate</div>
							<div class="text-lg font-bold text-emerald-400">{run.stats.win_rate}%</div>
						</div>
						<div class="bg-gray-800 rounded-lg p-3 text-center">
							<div class="text-xs text-gray-500">Trades</div>
							<div class="text-lg font-bold">{run.stats.total_trades}</div>
						</div>
						<div class="bg-gray-800 rounded-lg p-3 text-center">
							<div class="text-xs text-gray-500">Profit Factor</div>
							<div class="text-lg font-bold text-emerald-400">{run.stats.profit_factor}</div>
						</div>
						<div class="bg-gray-800 rounded-lg p-3 text-center">
							<div class="text-xs text-gray-500">Max DD</div>
							<div class="text-lg font-bold text-red-400">{run.stats.max_drawdown}%</div>
						</div>
						<div class="bg-gray-800 rounded-lg p-3 text-center">
							<div class="text-xs text-gray-500">Avg Win R</div>
							<div class="text-lg font-bold text-emerald-400">{run.stats.avg_win_rr?.toFixed(2)}</div>
						</div>
						<div class="bg-gray-800 rounded-lg p-3 text-center">
							<div class="text-xs text-gray-500">Avg Loss R</div>
							<div class="text-lg font-bold text-red-400">{run.stats.avg_loss_rr?.toFixed(2)}</div>
						</div>
						<div class="bg-gray-800 rounded-lg p-3 text-center">
							<div class="text-xs text-gray-500">Total P&L</div>
							<div class="text-lg font-bold {run.stats.total_pnl >= 0 ? 'text-emerald-400' : 'text-red-400'}">{formatCurrency(run.stats.total_pnl)}</div>
						</div>
					</div>

					<!-- Session breakdown -->
					<div class="flex gap-3 mt-3 text-xs text-gray-500">
						{#each Object.entries(run.stats.trades_by_session || {}) as [session, count]}
							<span>{session}: {count}</span>
						{/each}
					</div>
				{/if}
			</div>
		{/each}
	</div>
{/if}

<!-- Run Detail -->
{#if showDetail && selectedRun}
	<div class="fixed inset-0 bg-black/60 z-50 flex items-center justify-center p-4" onclick={closeDetail}>
		<div class="bg-gray-900 border border-gray-700 rounded-xl max-w-3xl w-full max-h-[85vh] overflow-y-auto p-6" onclick={(e) => e.stopPropagation()}>
			<div class="flex justify-between items-start mb-4">
				<h2 class="text-lg font-bold">
					{selectedRun.symbol} · {selectedRun.period || (selectedRun.months_back ? selectedRun.months_back + 'mo' : selectedRun.days_back ? selectedRun.days_back + 'd' : '?')} · {selectedRun.lot_size} lot · {formatCurrency(selectedRun.initial_capital || 10000)} capital
				</h2>
				<button onclick={closeDetail} class="text-gray-400 hover:text-white text-2xl leading-none">&times;</button>
			</div>

			<div class="flex items-center gap-4 mb-6 text-sm">
				<span class="px-2 py-0.5 rounded text-xs {selectedRun.status === 'completed' ? 'bg-emerald-900/30 text-emerald-300' : 'bg-red-900/30 text-red-300'}">
					{selectedRun.status}
				</span>
				<span class="text-gray-500">{formatDateTime(selectedRun.created_at)}</span>
			</div>

			{#if selectedRun.stats}
				<div class="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-7 gap-3 mb-6 text-sm">
					<div class="bg-gray-800 rounded-lg p-3 text-center">
						<div class="text-xs text-gray-500">Win Rate</div>
						<div class="text-lg font-bold text-emerald-400">{selectedRun.stats.win_rate}%</div>
					</div>
					<div class="bg-gray-800 rounded-lg p-3 text-center">
						<div class="text-xs text-gray-500">Trades</div>
						<div class="text-lg font-bold">{selectedRun.stats.total_trades}</div>
					</div>
					<div class="bg-gray-800 rounded-lg p-3 text-center">
						<div class="text-xs text-gray-500">Profit Factor</div>
						<div class="text-lg font-bold text-emerald-400">{selectedRun.stats.profit_factor}</div>
					</div>
					<div class="bg-gray-800 rounded-lg p-3 text-center">
						<div class="text-xs text-gray-500">Max DD</div>
						<div class="text-lg font-bold text-red-400">{selectedRun.stats.max_drawdown}%</div>
					</div>
					<div class="bg-gray-800 rounded-lg p-3 text-center">
						<div class="text-xs text-gray-500">Avg Win R</div>
						<div class="text-lg font-bold text-emerald-400">{selectedRun.stats.avg_win_rr?.toFixed(2)}</div>
					</div>
					<div class="bg-gray-800 rounded-lg p-3 text-center">
						<div class="text-xs text-gray-500">Avg Loss R</div>
						<div class="text-lg font-bold text-red-400">{selectedRun.stats.avg_loss_rr?.toFixed(2)}</div>
					</div>
					<div class="bg-gray-800 rounded-lg p-3 text-center">
						<div class="text-xs text-gray-500">Total P&L</div>
						<div class="text-lg font-bold {selectedRun.stats.total_pnl >= 0 ? 'text-emerald-400' : 'text-red-400'}">{formatCurrency(selectedRun.stats.total_pnl)}</div>
					</div>
				</div>

				<!-- Session breakdown -->
				<div class="flex gap-3 mb-6 text-xs text-gray-500">
					{#each Object.entries(selectedRun.stats.trades_by_session || {}) as [session, count]}
						<span>{session}: {count}</span>
					{/each}
				</div>

				<!-- Direction breakdown -->
				<div class="flex gap-6 mb-6 text-sm">
					<div class="bg-gray-800 rounded-lg px-4 py-2">
						<span class="text-gray-500">BUY:</span>
						<span class="font-medium text-emerald-400 ml-2">{selectedRun.stats.trades_by_direction?.BUY || 0}</span>
					</div>
					<div class="bg-gray-800 rounded-lg px-4 py-2">
						<span class="text-gray-500">SELL:</span>
						<span class="font-medium text-red-400 ml-2">{selectedRun.stats.trades_by_direction?.SELL || 0}</span>
					</div>
				</div>
			{/if}

			<!-- Equity Curve Chart -->
			{#if selectedRun.equity_curve?.length && selectedRun.stats}
				{@const chartData = drawEquityCurve(selectedRun.equity_curve, selectedRun.stats.initial_balance || 0)}
				{#if chartData}
					<h3 class="text-sm font-semibold text-gray-400 uppercase tracking-wider mb-3">Equity Curve</h3>
					{@const balY = chartData.initialBalanceY}
					<svg viewBox="0 0 600 220" class="w-full" style="background: #111827; border-radius: 8px;">
						<line x1="10" y1={balY} x2="590" y2={balY} stroke="#374151" stroke-width="1" stroke-dasharray="4 2" />
						<text x="5" y="15" fill="#6B7280" font-size="9">{chartData.maxEquity.toFixed(0)}</text>
						<text x="5" y="210" fill="#6B7280" font-size="9">{chartData.minEquity.toFixed(0)}</text>
						<text x="5" y={balY + 5} fill="#6B7280" font-size="9">{chartData.initialBalance.toFixed(0)}</text>
						<polyline
							points={chartData.points}
							fill="none"
							stroke={chartData.finalEquity >= chartData.initialBalance ? '#10B981' : '#EF4444'}
							stroke-width="1.5"
						/>
					</svg>
				{/if}
			{/if}

			<!-- Best / Worst Trades -->
			{#if selectedRun.stats?.best_trades?.length || selectedRun.stats?.worst_trades?.length}
				<div class="grid grid-cols-1 sm:grid-cols-2 gap-6 mt-6">
					{#if selectedRun.stats.best_trades?.length}
						<div>
							<h3 class="text-sm font-semibold text-emerald-400 mb-2">Top 5 Best Trades</h3>
							<div class="space-y-1">
								{#each selectedRun.stats.best_trades as trade}
									<div class="bg-gray-800 rounded px-3 py-1.5 flex justify-between text-xs">
										<span>{trade.direction || '—'}</span>
										<span class="text-emerald-400">{formatCurrency(trade.pnl)}</span>
									</div>
								{/each}
							</div>
						</div>
					{/if}
					{#if selectedRun.stats.worst_trades?.length}
						<div>
							<h3 class="text-sm font-semibold text-red-400 mb-2">Top 5 Worst Trades</h3>
							<div class="space-y-1">
								{#each selectedRun.stats.worst_trades as trade}
									<div class="bg-gray-800 rounded px-3 py-1.5 flex justify-between text-xs">
										<span>{trade.direction || '—'}</span>
										<span class="text-red-400">{formatCurrency(trade.pnl)}</span>
									</div>
								{/each}
							</div>
						</div>
					{/if}
				</div>
			{/if}

			<div class="mt-6 text-center">
				<button onclick={closeDetail} class="px-5 py-2 bg-gray-800 hover:bg-gray-700 border border-gray-700 rounded-lg text-sm text-gray-300 transition-colors">
					Close
				</button>
			</div>
		</div>
	</div>
{/if}
