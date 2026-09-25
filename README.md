# CloudGenix WAN Network Report

Enumerates all sites in a Prisma SD-WAN (CloudGenix) tenant and collects WAN network and IP address information for every element interface, writing the results to a CSV file.

## Prerequisites

- Python 3.7+
- An active Prisma SD-WAN / CloudGenix account
- `cloudgenix` Python SDK

```bash
pip install cloudgenix
```

## Usage

```
python cloudgenix_network_report.py [--token TOKEN] [--email EMAIL] [--password PASSWORD] [--output FILE]
```

### Arguments

| Argument | Description |
|---|---|
| `--token TOKEN` | Static API auth token (recommended for automation) |
| `--email EMAIL` | Login email address |
| `--password PASSWORD` | Login password (prompted securely if omitted) |
| `--output FILE` | Output CSV file path (default: `network_report.csv`) |

If no credentials are provided the script prompts interactively and lets you choose between token or email/password login.

### Examples

**Using an API token (recommended for scripts and automation):**

```bash
python cloudgenix_network_report.py --token "YOUR_AUTH_TOKEN"
```

**Custom output file:**

```bash
python cloudgenix_network_report.py --token "YOUR_AUTH_TOKEN" --output wan_report.csv
```

**Using email and password:**

```bash
python cloudgenix_network_report.py --email user@example.com --password YOUR_PASSWORD
```

**Interactive login (prompts for method and credentials):**

```bash
python cloudgenix_network_report.py
```

## Output

The report is written as a CSV with the following columns:

| Column | Description |
|---|---|
| `site_name` | Human-readable site name |
| `site_id` | Site UUID |
| `element_name` | ION device name |
| `element_id` | Element UUID |
| `interface_name` | Interface name (e.g. `wan0`, `lan0`) |
| `interface_role` | `wan-public`, `wan-private`, or `lan` |
| `wan_network_name` | Name of the associated WAN network |
| `wan_network_type` | `publicwan` or `privatewan` |
| `wan_label` | WAN interface label |
| `ip_address` | Configured IP address (blank if DHCP) |
| `prefix` | Prefix length |
| `subnet` | Calculated network/subnet in CIDR notation |

## Creating an API Token in Strata Cloud Manager

Static auth tokens are the recommended approach for automation. They are created directly from the Prisma SD-WAN web interface:

1. Log in to the **Prisma SD-WAN** portal (via Strata Cloud Manager or the standalone portal).
2. Navigate to **System → Access Management → Site Access → Auth Tokens**.
3. Click **Create Auth Token** and follow the prompts.
4. Copy the generated token and pass it to the script via `--token`.

### Documentation

- [Prisma SD-WAN Legacy API — Getting Started](https://pan.dev/sdwan/docs/legacy_getstarted/) — covers static token creation and how to authenticate against the CloudGenix controller API.
- [Prisma SD-WAN Python SDK — Getting Started](https://pan.dev/sdwan/docs/sdwan_gsg_sdk/) — covers SDK installation, authentication methods, and token usage.
- [CloudGenix Python SDK — GitHub](https://github.com/CloudGenix/sdk-python) — source code and additional examples.
- [Prisma SASE — Service Accounts & OAuth](https://pan.dev/sase/docs/service-accounts/) — for integrations using the unified SASE API with OAuth 2.0 service account tokens.
