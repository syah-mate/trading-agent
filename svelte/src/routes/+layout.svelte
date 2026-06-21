<script>
	import './layout.css';

	let { children } = $props();
</script>

<svelte:head>
	<title>AI Trading Agent</title>
	<meta name="description" content="AI Trading Agent Dashboard" />
</svelte:head>

<div class="min-h-screen bg-gray-950 text-gray-100">
	<!-- Navbar -->
	<nav class="border-b border-gray-800 bg-gray-900/80 backdrop-blur sticky top-0 z-50">
		<div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
			<div class="flex items-center justify-between h-14">
				<div class="flex items-center gap-6">
					<a href="/" class="text-lg font-bold text-emerald-400 hover:text-emerald-300 transition-colors">
						⚡ AI Trading Agent
					</a>
					<div class="hidden sm:flex items-center gap-1">
						<a href="/" class="px-3 py-1.5 rounded-md text-sm text-gray-300 hover:text-white hover:bg-gray-800 transition-colors">
							Dashboard
						</a>
						<a href="/trades" class="px-3 py-1.5 rounded-md text-sm text-gray-300 hover:text-white hover:bg-gray-800 transition-colors">
							Trades
						</a>
						<a href="/backtest" class="px-3 py-1.5 rounded-md text-sm text-gray-300 hover:text-white hover:bg-gray-800 transition-colors">
							Backtest
						</a>
						<a href="/config" class="px-3 py-1.5 rounded-md text-sm text-gray-300 hover:text-white hover:bg-gray-800 transition-colors">
							Config
						</a>
					</div>
				</div>
				<div class="flex items-center gap-3">
					<span class="text-xs text-gray-500">M15 · Volume Profile + Liquidity Sweep</span>
				</div>
			</div>
		</div>
	</nav>

	<!-- Main Content -->
	<main class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
		{@render children()}
	</main>
</div>
