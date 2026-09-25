#!/usr/bin/env python3
"""
CloudGenix WAN Network Report
Enumerates all sites and collects WAN network / IP address information,
writing results to a CSV file.
"""

import argparse
import csv
import getpass
import ipaddress
import sys

import cloudgenix

CSV_COLUMNS = [
    "site_name",
    "site_id",
    "element_name",
    "element_id",
    "interface_name",
    "interface_role",
    "wan_network_name",
    "wan_network_type",
    "wan_label",
    "ip_address",
    "prefix",
    "subnet",
]

SKIP_TYPES = {"loopback", "system"}
SKIP_NAMES = {"lo"}


def _fetch_all(sdk, resp):
    """
    Exhaust pagination for a CloudGenix list endpoint response.

    When more pages exist the API embeds a ``next_query`` object in the
    response body.  Passing it back as the body of a new GET to the same URL
    (CloudGenix's GET-with-body pagination pattern) returns the next page.
    Repeats until ``next_query`` is absent.

    Returns the combined ``items`` list across all pages.
    """
    if not resp.cgx_status:
        return []
    all_items = list(resp.cgx_content.get("items", []))
    next_query = resp.cgx_content.get("next_query")
    while next_query:
        resp = sdk.rest_call(resp.url, "get", data={"next_query": next_query})
        if not resp.cgx_status:
            break
        all_items.extend(resp.cgx_content.get("items", []))
        next_query = resp.cgx_content.get("next_query")
    return all_items


def parse_args():
    parser = argparse.ArgumentParser(
        description="Generate a WAN network report for all CloudGenix/Prisma SD-WAN sites."
    )
    parser.add_argument("--token", help="API auth token")
    parser.add_argument("--email", help="Login email address")
    parser.add_argument("--password", help="Login password")
    parser.add_argument(
        "--output",
        default="network_report.csv",
        help="Output CSV file path (default: network_report.csv)",
    )
    return parser.parse_args()


def authenticate(sdk, args):
    success = False

    if args.token:
        success = sdk.interactive.use_token(args.token)
    elif args.email:
        password = args.password or getpass.getpass(f"Password for {args.email}: ")
        success = sdk.interactive.login(email=args.email, password=password)
    else:
        print("No credentials provided. Choose authentication method:")
        print("  1) API Token")
        print("  2) Email / Password")
        choice = input("Enter 1 or 2: ").strip()
        if choice == "1":
            token = input("Enter API token: ").strip()
            success = sdk.interactive.use_token(token)
        elif choice == "2":
            email = input("Enter email: ").strip()
            password = getpass.getpass("Enter password: ")
            success = sdk.interactive.login(email=email, password=password)
        else:
            print("Invalid choice.", file=sys.stderr)
            sys.exit(1)

    if not success:
        print("Authentication failed.", file=sys.stderr)
        sys.exit(1)

    tenant_name = sdk.tenant_name if sdk.tenant_name else sdk.tenant_id
    print(f"Authenticated. Tenant: {tenant_name}")


def load_wannetworks(sdk):
    wn_map = {}
    resp = sdk.get.wannetworks()
    if not resp.cgx_status:
        raise cloudgenix.CloudGenixAPIError(f"Failed to load WAN networks: {resp.cgx_errors}")
    for item in _fetch_all(sdk, resp):
        wn_map[item["id"]] = {
            "name": item.get("name", ""),
            "type": item.get("type", ""),
        }
    return wn_map


def load_waninterfacelabels(sdk):
    label_map = {}
    resp = sdk.get.waninterfacelabels()
    if not resp.cgx_status:
        raise cloudgenix.CloudGenixAPIError(
            f"Failed to load WAN interface labels: {resp.cgx_errors}"
        )
    for item in _fetch_all(sdk, resp):
        label_map[item["id"]] = item.get("name", "")
    return label_map


def load_sites(sdk):
    resp = sdk.get.sites()
    if not resp.cgx_status:
        raise cloudgenix.CloudGenixAPIError(f"Failed to load sites: {resp.cgx_errors}")
    return _fetch_all(sdk, resp)


def load_elements(sdk):
    elem_map = {}
    resp = sdk.get.elements()
    if not resp.cgx_status:
        raise cloudgenix.CloudGenixAPIError(f"Failed to load elements: {resp.cgx_errors}")
    for item in _fetch_all(sdk, resp):
        site_id = item.get("site_id")
        if site_id:
            elem_map.setdefault(site_id, []).append(item)
    return elem_map


def load_waninterfaces(sdk, site_id):
    swi_map = {}
    resp = sdk.get.waninterfaces(site_id)
    if not resp.cgx_status:
        # Gracefully handle 404 or other errors (site may have no WAN interfaces)
        return swi_map
    for item in _fetch_all(sdk, resp):
        swi_map[item["id"]] = item
    return swi_map


def get_interface_addresses(iface):
    """
    Extract IP addresses from an interface dict.

    CloudGenix API versions differ in where they store interface IPs:
    - Some return a top-level ``addresses`` list with {address, prefix} dicts.
    - Most return a nested ``ipv4_config.static_config`` object when the
      interface is statically configured.

    DHCP-configured interfaces have no stored IP, so an empty list is
    returned for them; the caller emits a blank-IP row in that case.
    """
    # Method 1: top-level addresses list (some API / firmware versions)
    addresses = iface.get("addresses") or []
    if addresses and isinstance(addresses, list):
        normalized = []
        for a in addresses:
            if not isinstance(a, dict):
                continue
            # Field key may be "address" or "ip_address" depending on version
            ip = a.get("address") or a.get("ip_address", "")
            prefix = a.get("prefix", "")
            normalized.append({"address": ip, "prefix": prefix})
        if normalized:
            return normalized

    # Method 2: ipv4_config.static_config (standard CloudGenix / Prisma SD-WAN)
    ipv4 = iface.get("ipv4_config") or {}
    if isinstance(ipv4, dict) and ipv4.get("type") == "static":
        static = ipv4.get("static_config") or {}
        if isinstance(static, dict):
            ip = static.get("address", "")
            prefix = static.get("prefix", "")
            if ip:
                return [{"address": ip, "prefix": prefix}]

    return []


def calc_subnet(ip, prefix):
    if not ip or prefix is None or prefix == "":
        return ""
    try:
        network = ipaddress.ip_interface(f"{ip}/{prefix}").network
        return str(network)
    except ValueError:
        return ""


def process_element(sdk, site, element, swi_map, wn_map, label_map):
    rows = []
    site_id = site["id"]
    site_name = site.get("name", "")
    element_id = element["id"]
    element_name = element.get("name", "")

    resp = sdk.get.interfaces(site_id, element_id)
    if not resp.cgx_status:
        print(
            f"  WARN: Could not load interfaces for element {element_name} ({element_id}): "
            f"{resp.cgx_errors}",
            file=sys.stderr,
        )
        return rows

    interfaces = _fetch_all(sdk, resp)

    for iface in interfaces:
        iface_name = iface.get("name", "")
        iface_type = iface.get("type", "")

        # Skip loopback/system interfaces
        if iface_type in SKIP_TYPES or iface_name in SKIP_NAMES:
            continue

        # Collect SWI IDs from both modern (list) and legacy (scalar) fields
        swi_ids = set()
        modern = iface.get("site_wan_interface_ids") or []
        if isinstance(modern, list):
            swi_ids.update(swi_id for swi_id in modern if swi_id)
        legacy = iface.get("site_wan_interface_id")
        if legacy:
            swi_ids.add(legacy)

        addresses = get_interface_addresses(iface)

        if swi_ids:
            # WAN interface
            for swi_id in swi_ids:
                swi = swi_map.get(swi_id, {})
                network_id = swi.get("network_id", "")
                label_id = swi.get("label_id", "")

                wn_info = wn_map.get(network_id, {})
                wan_network_name = wn_info.get("name", "")
                wan_network_type = wn_info.get("type", "")
                wan_label = label_map.get(label_id, "")

                # Determine role from network type
                if wan_network_type == "publicwan":
                    interface_role = "wan-public"
                else:
                    interface_role = "wan-private"

                if addresses:
                    for addr in addresses:
                        ip = addr.get("address", "")
                        prefix = addr.get("prefix", "")
                        subnet = calc_subnet(ip, prefix)
                        rows.append(
                            {
                                "site_name": site_name,
                                "site_id": site_id,
                                "element_name": element_name,
                                "element_id": element_id,
                                "interface_name": iface_name,
                                "interface_role": interface_role,
                                "wan_network_name": wan_network_name,
                                "wan_network_type": wan_network_type,
                                "wan_label": wan_label,
                                "ip_address": ip,
                                "prefix": prefix,
                                "subnet": subnet,
                            }
                        )
                else:
                    # DHCP or unconfigured — still emit a row
                    rows.append(
                        {
                            "site_name": site_name,
                            "site_id": site_id,
                            "element_name": element_name,
                            "element_id": element_id,
                            "interface_name": iface_name,
                            "interface_role": interface_role,
                            "wan_network_name": wan_network_name,
                            "wan_network_type": wan_network_type,
                            "wan_label": wan_label,
                            "ip_address": "",
                            "prefix": "",
                            "subnet": "",
                        }
                    )
        else:
            # LAN interface — only emit if there are addresses
            if not addresses:
                continue
            for addr in addresses:
                ip = addr.get("address", "")
                prefix = addr.get("prefix", "")
                subnet = calc_subnet(ip, prefix)
                rows.append(
                    {
                        "site_name": site_name,
                        "site_id": site_id,
                        "element_name": element_name,
                        "element_id": element_id,
                        "interface_name": iface_name,
                        "interface_role": "lan",
                        "wan_network_name": "",
                        "wan_network_type": "",
                        "wan_label": "",
                        "ip_address": ip,
                        "prefix": prefix,
                        "subnet": subnet,
                    }
                )

    return rows


def write_csv(rows, output_path):
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main():
    args = parse_args()

    sdk = cloudgenix.API(update_check=False)
    authenticate(sdk, args)

    print("Loading WAN networks, WAN interface labels, and elements...")
    wn_map = load_wannetworks(sdk)
    label_map = load_waninterfacelabels(sdk)
    elem_map = load_elements(sdk)

    sites = load_sites(sdk)
    print(f"Found {len(sites)} site(s).")

    all_rows = []

    for site in sites:
        site_id = site["id"]
        site_name = site.get("name", site_id)

        swi_map = load_waninterfaces(sdk, site_id)
        if not swi_map:
            print(f"  Site '{site_name}': no WAN interfaces, skipping.")
            continue

        elements = elem_map.get(site_id, [])
        if not elements:
            print(f"  Site '{site_name}': no elements, skipping.")
            continue

        print(f"  Site '{site_name}': {len(elements)} element(s), {len(swi_map)} WAN interface(s).")

        for element in elements:
            try:
                rows = process_element(sdk, site, element, swi_map, wn_map, label_map)
                all_rows.extend(rows)
                elem_name = element.get("name", element["id"])
                print(f"    Element '{elem_name}': {len(rows)} row(s) collected.")
            except Exception as exc:
                elem_name = element.get("name", element.get("id", "unknown"))
                print(
                    f"    WARN: Error processing element '{elem_name}': {exc}",
                    file=sys.stderr,
                )

    write_csv(all_rows, args.output)
    print(f"\nReport written to '{args.output}' ({len(all_rows)} row(s) total).")

    sdk.interactive.logout()


if __name__ == "__main__":
    main()
