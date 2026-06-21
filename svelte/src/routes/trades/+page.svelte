<script>
	import { fetchTrades, fetchTradeByTicket } from '$lib/api';

	let trades = $state([]);
	let loading = $state(true);
	let error = $state('');
	let selectedTrade = $state(null);
	let modalOpen = $state(false);

	let filterDirection = $state('');
	let filterResult = $state('');
	let filterDateFrom = $state('');
	let filterDateTo = $state('');

	async function loadTrades() {
		loading = true;
		error = '';
		try {
			trades = await fetchTrades(200);
		} catch (e) {
			error = e.message || 'Gagal fetch trades';
		} finally {
			loading = false;
		}
	}

	async function openDetail(ticket) {
		try {
			selectedTrade = await fetchTradeByTicket(ticket);
			modalOpen = true;
		} catch (e) {
			alert('Gagal load detail: ' + e.message);
		}
	}

	function closeModal() {
		modalOpen = false;
		selectedTrade = null;
	}

	$effect(() => { loadTrades(); });

	function formatCurrency(val) {
		if (val == null) return '$0.00';
		return '$' + Number(val).toLocaleString('en-US', { minimumFractionDigits: 2 });
	}

	function formatDateTime(iso) {
		if (!iso) return '—';
		return new Date(iso).toLocaleString('id-ID', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
	}

	let filteredTrades = $derived(trades.filter(t => {
		if (filterDirection && t.direction !== filterDirection) return false;
		if (filterResult === 'win' && (t.pnl == null || t.pnl <= 0)) return false;
		if (filterResult === 'loss' && (t.pnl == null || t.pnl >= 0)) return false;
		if (filterDateFrom && new Date(t.opened_at) < new Date(filterDateFrom)) return false;
		if (filterDateTo && new Date(t.opened_at) > new Date(filterDateTo + 'T23:59:59')) return false;
		return true;
	}));
</script>

{#if loading}
	<div class="flex items-center justify-center py-20">
		<div class="animate-spin rounded-full h-8 w-8 border-b-2 border-emerald-400"></div>
		<span class="ml-3 text-gray-400">Loading trades...</span>
	</div>
{:else if error}
	<div class="bg-red-900/30 border border-red-700 rounded-lg p-6 text-center">
		<p class="text-red-300">⚠️ {error}</p>
		<button onclick={loadTrades} class="mt-4 px-4 py-2 bg-red-700 hover:bg-red-600 rounded-lg text-sm">Retry</button>
	</div>
{:else}
	<h1 class="text-2xl font-bold mb-6">Trade History</h1>

	<!-- Filters -->
	<div class="flex flex-wrap gap-3 mb-6">
		<select bind:value={filterDirection} class="bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-sm">
			<option value="">All Directions</option>
			<option value="BUY">BUY</option>
			<option value="SELL">SELL</option>
		</select>
		<select bind:value={filterResult} class="bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-sm">
			<option value="">All Results</option>
			<option value="win">Win</option>
			<option value="loss">Loss</option>
		</select>
		<div class="flex items-center gap-2">
			<label class="text-xs text-gray-500">From:</label>
			<input
				type="date"
				bind:value={filterDateFrom}
				class="bg-gray-900 border border-gray-700 rounded-lg px-2 py-1.5 text-sm text-gray-300"
			/>
		</div>
		<div class="flex items-center gap-2">
			<label class="text-xs text-gray-500">To:</label>
			<input
				type="date"
				bind:value={filterDateTo}
				class="bg-gray-900 border border-gray-700 rounded-lg px-2 py-1.5 text-sm text-gray-300"
			/>
		</div>
		<button
			onclick={() => { filterDateFrom = ''; filterDateTo = ''; filterDirection = ''; filterResult = ''; }}
			class="px-3 py-1.5 bg-gray-800 hover:bg-gray-700 border border-gray-700 rounded-lg text-xs text-gray-400 transition-colors"
		>
			Reset Filters
		</button>
		<span class="text-sm text-gray-500 self-center ml-auto">
			{filteredTrades.length} trades
		</span>
	</div>

	<!-- Table -->
	<div class="overflow-x-auto">
		<table class="w-full text-sm">
			<thead>
				<tr class="text-left text-gray-400 border-b border-gray-800">
					<th class="pb-3 pr-4">Ticket</th>
					<th class="pb-3 pr-4">Direction</th>
					<th class="pb-3 pr-4">Entry</th>
					<th class="pb-3 pr-4">SL</th>
					<th class="pb-3 pr-4">TP</th>
					<th class="pb-3 pr-4">Opened</th>
					<th class="pb-3 pr-4">Exit</th>
					<th class="pb-3 pr-4">P&L</th>
					<th class="pb-3"></th>
				</tr>
			</thead>
			<tbody>
				{#each filteredTrades as trade}
					<tr class="border-b border-gray-800/50 hover:bg-gray-900/50 transition-colors">
						<td class="py-3 pr-4 text-gray-500">#{trade.ticket}</td>
						<td class="py-3 pr-4">
							<span class="px-2 py-0.5 rounded text-xs font-medium {trade.direction === 'BUY' ? 'bg-emerald-900/50 text-emerald-400' : 'bg-red-900/50 text-red-400'}">
								{trade.direction}
							</span>
						</td>
						<td class="py-3 pr-4 font-mono">{trade.entry_price?.toFixed(4)}</td>
						<td class="py-3 pr-4 font-mono text-red-400">{trade.sl?.toFixed(4) || '—'}</td>
						<td class="py-3 pr-4 font-mono text-emerald-400">{trade.tp?.toFixed(4) || '—'}</td>
						<td class="py-3 pr-4 text-gray-400">{formatDateTime(trade.opened_at)}</td>
						<td class="py-3 pr-4 text-gray-400">{trade.exit_reason || (trade.status === 'open' ? 'Open' : '—')}</td>
						<td class="py-3 pr-4 font-mono {trade.pnl >= 0 ? 'text-emerald-400' : 'text-red-400'}">
							{trade.pnl != null ? formatCurrency(trade.pnl) : '—'}
						</td>
						<td class="py-3">
							<button onclick={() => openDetail(trade.ticket)} class="text-xs text-blue-400 hover:text-blue-300 underline">
								Detail
							</button>
						</td>
					</tr>
				{/each}
			</tbody>
		</table>
	</div>

	<!-- Modal Detail -->
	{#if modalOpen && selectedTrade}
		<div class="fixed inset-0 bg-black/60 z-50 flex items-center justify-center p-4" onclick={closeModal}>
			<div class="bg-gray-900 border border-gray-700 rounded-xl max-w-2xl w-full max-h-[80vh] overflow-y-auto p-6" onclick={(e) => e.stopPropagation()}>
				<div class="flex justify-between items-start mb-4">
					<h2 class="text-lg font-bold">Trade #{selectedTrade.ticket}</h2>
					<button onclick={closeModal} class="text-gray-400 hover:text-white text-2xl leading-none">&times;</button>
				</div>

				<div class="grid grid-cols-2 gap-3 mb-6 text-sm">
					<div><span class="text-gray-500">Direction:</span> <span class="font-medium">{selectedTrade.direction}</span></div>
					<div><span class="text-gray-500">Status:</span> <span class="font-medium">{selectedTrade.status}</span></div>
					<div><span class="text-gray-500">Entry:</span> <span class="font-mono">{selectedTrade.entry_price?.toFixed(4)}</span></div>
					<div><span class="text-gray-500">SL:</span> <span class="font-mono text-red-400">{selectedTrade.sl?.toFixed(4)}</span></div>
					<div><span class="text-gray-500">TP:</span> <span class="font-mono text-emerald-400">{selectedTrade.tp?.toFixed(4)}</span></div>
					<div><span class="text-gray-500">P&L:</span> <span class="font-mono {selectedTrade.pnl >= 0 ? 'text-emerald-400' : 'text-red-400'}">{formatCurrency(selectedTrade.pnl)}</span></div>
					<div><span class="text-gray-500">Opened:</span> {formatDateTime(selectedTrade.opened_at)}</div>
					<div><span class="text-gray-500">Confidence:</span> {selectedTrade.confidence}%</div>
					<div><span class="text-gray-500">Session:</span> {selectedTrade.session || '—'}</div>
					<div><span class="text-gray-500">Reason:</span> {selectedTrade.entry_reason || '—'}</div>
				</div>

				<!-- Monitoring Log -->
				<h3 class="text-sm font-semibold text-gray-400 uppercase tracking-wider mb-3">Monitoring Log</h3>
				{#if selectedTrade.monitoring_log?.length}
					<div class="space-y-2">
						{#each selectedTrade.monitoring_log as log}
							<div class="bg-gray-800 rounded-lg p-3 text-sm">
								<div class="flex justify-between mb-1">
									<span class="font-medium text-gray-300">{log.decision || '—'}</span>
									<span class="text-xs text-gray-500">{formatDateTime(log.monitored_at || log.timestamp)}</span>
								</div>
								<p class="text-gray-400">{log.reasoning || 'No reasoning'}</p>
							</div>
						{/each}
					</div>
				{:else}
					<p class="text-gray-500 text-sm">No monitoring decisions yet</p>
				{/if}
			</div>
		</div>
	{/if}
{/if}
