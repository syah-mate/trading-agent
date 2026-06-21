<script>
	import { fetchBacktestRuns, startBacktest, fetchBacktestProgress } from '$lib/api';

	let runs = $state([]);
	let loading = $state(true);
	let error = $state('');

	// Form
	let symbol = $state('XAUUSD');
	let monthsBack = $state(3);
	let lotSize = $state(0.01);

	// Running state
	let runningId = $state(null);
	let progress = $state(null);
	let pollingInterval = $state(null);

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
			const { run_id } = await startBacktest({
				symbol,
				timeframe: 'M15',
				months_back: monthsBack,
				lot_size: lotSize
			});
			runningId = run_id;
			// Start polling
			pollingInterval = setInterval(async () => {
				try {
					progress = await fetchBacktestProgress(run_id);
					if (progress.status === 'completed' || progress.status === 'error') {
						clearInterval(pollingInterval);
						pollingInterval = null;
						loadRuns();
					}
				} catch (e) { /* ignore */ }
			}, 3000);
		} catch (e) {
			alert('Gagal start backtest: ' + e.message);
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
			<label class="text-sm text-gray-400 block mb-1">Months Back</label>
			<input type="range" min="1" max="6" bind:value={monthsBack} class="w-full" />
			<span class="text-sm text-gray-500">{monthsBack} months</span>
		</div>
		<div>
			<label class="text-sm text-gray-400 block mb-1">Lot Size</label>
			<input type="number" step="0.01" min="0.01" bind:value={lotSize} class="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm" />
		</div>
		<div class="flex items-end">
			<button
				onclick={runBacktest}
				disabled={runningId !== null}
				class="w-full px-4 py-2 bg-emerald-600 hover:bg-emerald-500 disabled:bg-gray-700 disabled:text-gray-500 rounded-lg text-sm font-medium transition-colors"
			>
				{runningId ? 'Running...' : '▶ Run Backtest'}
			</button>
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
						<span class="text-sm font-medium">{run.symbol} · {run.months_back}mo · {run.lot_size} lot</span>
						<span class="ml-3 px-2 py-0.5 rounded text-xs {run.status === 'completed' ? 'bg-emerald-900/30 text-emerald-300' : run.status === 'error' ? 'bg-red-900/30 text-red-300' : 'bg-blue-900/30 text-blue-300'}">
							{run.status}
						</span>
					</div>
					<span class="text-xs text-gray-500">{formatDateTime(run.created_at)}</span>
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
