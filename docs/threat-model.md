# Threat Model

## System boundary

MCP DriftGuard sits on the MCP client / host side between tool discovery and exposure of a tool definition to the LLM.

The server is not assumed to be honest. A trusted baseline is established after installation-time review or explicit approval. Later observations are compared with the trusted version or the most recently approved version.

## In scope

- tool-description poisoning
- schema / metadata poisoning
- rug-pull updates after initial trust
- parameter and default-value manipulation
- capability or permission expansion
- stealthy semantic paraphrases
- hidden cross-tool instructions
- tool shadowing / redirection signals
- cumulative low-amplitude drift across versions

## Out of scope for the first version

- malware inside MCP server binaries
- OAuth implementation vulnerabilities
- stolen cryptographic keys
- arbitrary operating-system exploitation
- malicious tool outputs when the tool definition itself did not change

Those threats require complementary controls and are intentionally separated from this project's version-aware schema-change classifier.

## Trust assumptions

1. The detector can observe the complete tool definition returned to the host.
2. The local snapshot store is trusted for the initial prototype.
3. The detector runs before a changed definition is approved for normal invocation.
4. A previously approved definition is a useful reference point, but approval does not imply the server remains trustworthy.

## Primary attacker goal

Change a previously trusted tool definition so that the host or model grants new authority, exposes sensitive data, follows hidden instructions, prefers a malicious tool, or otherwise performs behavior outside the user's earlier consent.

## Security objective

Classify the **meaning and security significance of the change**, rather than merely detecting that bytes changed.
