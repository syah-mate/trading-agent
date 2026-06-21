<script>
	import { fetchStatus, fetchSignals, fetchTrades } from '$lib/api';

	let status = $state(null);
	let signals = $state([]);
	let trades = $state([]);
	let loading = $state(true);
	let error = $state('');

	async function loadData() {
		loading = true;
		error = '';
		try {
			[status, signals, trades] = await Promise.all([
				fetchStatus(),
				fetchSignals(10),
				fetchTrades(5)
			]);
		} catch (e) {
			error = e.message || 'Gagal fetch data dari API';
		} finally {
			loading = false;
		}
	}

	$effect(() => { loadData(); });

	function formatCurrency(val) {
		if (val == null) return '$0.00';
		return '$' + Number(val).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
	}

	function formatDateTime(iso) {
		if (!iso) return '—';
		return new Date(iso).toLocaleString('id-ID', { hour: '2-digit', minute: '2-digit', second: '2-digit', day: 'numeric', month: 'short' });
	}
</script>

{#if loading}
	<div class="flex items-center justify-center py-20">
		<div class="animate-spin rounded-full h-8 w-8 border-b-2 border-emerald-400"></div>
		<span class="ml-3 text-gray-400">Loading dashboard...</span>
	</div>
{:else if error}
	<div class="bg-red-900/30 border border-red-700 rounded-lg p-6 text-center">
		<p class="text-red-300 text-lg">⚠️ {error}</p>
		<button onclick={loadData} class="mt-4 px-4 py-2 bg-red-700 hover:bg-red-600 rounded-lg text-sm transition-colors">
			Retry
		</button>
	</div>
{:else}
	<!-- Agent Status -->
	<div class="mb-8">
		<h2 class="text-sm font-semibold text-gray-400 uppercase tracking-wider mb-4">Agent Status</h2>
		<div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
			<div class="bg-gray-900 border border-gray-800 rounded-xl p-5">
				<div class="flex items-center gap-3">
					<div class="w-3 h-3 rounded-full {status?.agent_running ? 'bg-emerald-400 animate-pulse' : 'bg-gray-600'}" />
					<span class="text-sm text-gray-400">Status</span>
				</div>
				<p class="text-lg font-semibold mt-2">{status?.agent_running ? 'Running' : 'Stopped'}</p>
			</div>
			<div class="bg-gray-900 border border-gray-800 rounded-xl p-5">
				<span class="text-sm text-gray-400">Last Cycle</span>
				<p class="text-lg font-semibold mt-2">{formatDateTime(status?.last_cycle_at)}</p>
			</div>
			<div class="bg-gray-900 border border-gray-800 rounded-xl p-5">
				<span class="text-sm text-gray-400">Open Positions</span>
				<p class="text-2xl font-bold mt-2 text-emerald-400">{status?.open_positions ?? 0}</p>
			</div>
			<div class="bg-gray-900 border border-gray-800 rounded-xl p-5">
				<span class="text-sm text-gray-400">Equity</span>
				<p class="text-2xl font-bold mt-2">{formatCurrency(status?.account?.equity)}</p>
			</div>
		</div>
		<div class="grid grid-cols-2 lg:grid-cols-4 gap-3 mt-3">
			<div class="bg-gray-900/50 rounded-lg px-4 py-2 flex justify-between">
				<span class="text-xs text-gray-500">Balance</span>
				<span class="text-sm font-medium">{formatCurrency(status?.account?.balance)}</span>
			</div>
			<div class="bg-gray-900/50 rounded-lg px-4 py-2 flex justify-between">
				<span class="text-xs text-gray-500">Margin</span>
				<span class="text-sm font-medium">{formatCurrency(status?.account?.margin)}</span>
			</div>
			<div class="bg-gray-900/50 rounded-lg px-4 py-2 flex justify-between">
				<span class="text-xs text-gray-500">Free Margin</span>
				<span class="text-sm font-medium">{formatCurrency(status?.account?.free_margin)}</span>
			</div>
		</div>
	</div>

	<div class="grid grid-cols-1 lg:grid-cols-2 gap-8">
		<!-- Recent Signals -->
		<div>
			<h2 class="text-sm font-semibold text-gray-400 uppercase tracking-wider mb-4">Recent Signals</h2>
			<div class="space-y-3">
				{#if signals.length === 0}
					<p class="text-gray-500 text-sm py-4">No signals yet</p>
				{:else}
					{#each signals as signal}
						<div class="bg-gray-900 border border-gray-800 rounded-lg p-4">
							<div class="flex items-center justify-between mb-2">
								<div class="flex items-center gap-2">
									<span class="px-2 py-0.5 rounded text-xs font-medium {signal.direction === 'BUY' ? 'bg-emerald-900/50 text-emerald-400' : signal.direction === 'SELL' ? 'bg-red-900/50 text-red-400' : 'bg-gray-800 text-gray-400'}">
										{signal.direction || 'NONE'}
									</span>
									<span class="text-xs text-gray-500">{formatDateTime(signal.evaluated_at || signal.created_at)}</span>
								</div>
								<span class="text-xs px-2 py-0.5 rounded {signal.is_valid ? 'bg-emerald-900/30 text-emerald-300' : 'bg-red-900/30 text-red-300'}">
									{signal.is_valid ? 'Valid' : 'Rejected'}
								</span>
							</div>
							<p class="text-sm text-gray-300">{signal.entry_reason || signal.rejection_reason || '—'}</p>
							<div class="flex gap-4 mt-2 text-xs text-gray-500">
								<span>Confidence: {signal.confidence ?? '—'}%</span>
								<span>Session: {signal.session || '—'}</span>
							</div>
						</div>
					{/each}
				{/if}
			</div>
		</div>

		<!-- Recent Trades -->
		<div>
			<h2 class="text-sm font-semibold text-gray-400 uppercase tracking-wider mb-4">Recent Trades</h2>
			<div class="space-y-3">
				{#if trades.length === 0}
					<p class="text-gray-500 text-sm py-4">No trades yet</p>
				{:else}
					{#each trades as trade}
						<div class="bg-gray-900 border border-gray-800 rounded-lg p-4">
							<div class="flex items-center justify-between mb-2">
								<div class="flex items-center gap-2">
									<span class="px-2 py-0.5 rounded text-xs font-medium {trade.direction === 'BUY' ? 'bg-emerald-900/50 text-emerald-400' : 'bg-red-900/50 text-red-400'}">
										{trade.direction}
									</span>
									<span class="text-xs text-gray-500">#{trade.ticket}</span>
								</div>
								<span class="text-xs px-2 py-0.5 rounded {trade.status === 'open' ? 'bg-blue-900/30 text-blue-300' : 'bg-gray-800 text-gray-400'}">
									{trade.status || 'open'}
								</span>
							</div>
							<div class="grid grid-cols-3 gap-2 text-sm">
								<div><span class="text-gray-500">Entry:</span> <span class="text-gray-200">{trade.entry_price?.toFixed(4)}</span></div>
								<div><span class="text-gray-500">SL:</span> <span class="text-red-400">{trade.sl?.toFixed(4)}</span></div>
								<div><span class="text-gray-500">TP:</span> <span class="text-emerald-400">{trade.tp?.toFixed(4)}</span></div>
							</div>
							{#if trade.pnl != null}
								<div class="mt-2 text-sm {trade.pnl >= 0 ? 'text-emerald-400' : 'text-red-400'}">
									P&L: {formatCurrency(trade.pnl)}
								</div>
							{/if}
						</div>
					{/each}
				{/if}
			</div>
		</div>
	</div>

	<!-- Refresh Button -->
	<div class="mt-8 text-center">
		<button onclick={loadData} class="px-5 py-2 bg-gray-800 hover:bg-gray-700 border border-gray-700 rounded-lg text-sm text-gray-300 transition-colors">
			🔄 Refresh Data
		</button>
	</div>
{/if}
