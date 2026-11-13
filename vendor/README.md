# Bundled companion adapters

These allowlisted modules originate in the same project’s Private AI companion app. They provide encrypted storage compatibility, macOS Keychain access and the read-only Google connector. The rest of the companion application is not required or bundled. `network.py` contains only the redirect blocker used by Google.

Google application credentials are excluded from the public repository and default Mac package. The Google connector remains available for installations with an existing encrypted configuration or a separately configured release. New Gmail sign-in is disabled when no application identity is available. Imports and native AI connections do not need Gmail.

Never add vaults, account tokens, personal exports, device keys or runtime state to this directory. All code is covered by the repository MIT license.
