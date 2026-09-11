(function () {
	'use strict'

	const webroot = (window._oc_webroot || '').replace(/\/$/, '')
	const configUrl = `${webroot}/index.php/apps/public_share_domain/config`

	function rewriteShareUrl(value, publicOrigin) {
		if (typeof value !== 'string') {
			return value
		}

		try {
			const source = new URL(value, window.location.href)
			if (source.origin !== window.location.origin) {
				return value
			}

			const relativePath = webroot && source.pathname.startsWith(webroot)
				? source.pathname.slice(webroot.length)
				: source.pathname
			if (!/^\/(?:index\.php\/)?s\/[^/]+\/?$/.test(relativePath)) {
				return value
			}

			const destination = new URL(publicOrigin)
			destination.pathname = source.pathname
			destination.search = source.search
			destination.hash = source.hash
			return destination.toString()
		} catch (error) {
			return value
		}
	}

	async function install() {
		const response = await fetch(configUrl, {
			credentials: 'same-origin',
			headers: { 'OCS-APIRequest': 'true' },
		})
		if (!response.ok) {
			return
		}

		const { publicOrigin } = await response.json()
		const parsedOrigin = new URL(publicOrigin)
		if (parsedOrigin.protocol !== 'https:') {
			return
		}

		if (navigator.clipboard && typeof navigator.clipboard.writeText === 'function') {
			const clipboard = navigator.clipboard
			const originalWriteText = clipboard.writeText.bind(clipboard)
			Object.defineProperty(clipboard, 'writeText', {
				configurable: true,
				value(value) {
					return originalWriteText(rewriteShareUrl(value, publicOrigin))
				},
			})
		}

		const originalPrompt = window.prompt.bind(window)
		window.prompt = function (message, defaultValue) {
			return originalPrompt(message, rewriteShareUrl(defaultValue, publicOrigin))
		}
	}

	install().catch(() => {})
})()
