async function loadInventory() {
  const response = await fetch("data/inventory.json", { cache: "no-store" });
  if (!response.ok) throw new Error(`Failed to load inventory (${response.status})`);
  return response.json();
}

function fmt(value) {
  if (value === null || value === undefined || value === "") return "—";
  return String(value);
}

function badge(status) {
  if (status === "ok") return '<span class="badge ok">reachable</span>';
  if (status === "unreachable") return '<span class="badge bad">unreachable</span>';
  return `<span class="badge warn">${status}</span>`;
}

function renderTotals(data) {
  const t = data.totals || {};
  const items = [
    ["Sites scanned", t.sites_scanned ?? data.site_count ?? 0],
    ["Sites reachable", t.sites_reachable ?? 0],
    ["Aruba switches", t.aruba_switches ?? 0],
    ["Up interfaces", t.up_interfaces ?? 0],
  ];
  document.getElementById("totals").innerHTML = items
    .map(
      ([label, value]) => `
      <article class="stat">
        <div class="label">${label}</div>
        <div class="value">${value}</div>
      </article>`
    )
    .join("");
}

function renderSwitchRows(switches) {
  if (!switches || !switches.length) {
    return '<p class="empty">No switches discovered on this site.</p>';
  }
  const rows = switches
    .map(
      (sw) => `
      <tr>
        <td data-label="Hostname" class="mono">${fmt(sw.hostname)}</td>
        <td data-label="IP" class="mono">${fmt(sw.ip)}</td>
        <td data-label="Model">${fmt(sw.model)}</td>
        <td data-label="Software" class="mono">${fmt(sw.software)}</td>
        <td data-label="Serial" class="mono">${fmt(sw.serial)}</td>
        <td data-label="Up ifaces" class="mono">${fmt(sw.up_interfaces)}</td>
        <td data-label="VLANs" class="mono">${fmt(sw.vlan_count)}</td>
        <td data-label="Auth">${fmt(sw.profile_used)}</td>
      </tr>`
    )
    .join("");
  return `
    <table>
      <thead>
        <tr>
          <th>Hostname</th><th>IP</th><th>Model</th><th>Software</th>
          <th>Serial</th><th>Up ifaces</th><th>VLANs</th><th>Auth</th>
        </tr>
      </thead>
      <tbody>${rows}</tbody>
    </table>`;
}

function renderSites(data) {
  document.getElementById("sites").innerHTML = (data.sites || [])
    .map((site) => {
      const message = site.message
        ? `<p class="message">${site.message}</p>`
        : "";
      return `
      <article class="site">
        <div class="site-head">
          <div>
            <h2>${site.name}<span class="abbr">${fmt(site.abbreviation)}</span></h2>
            ${badge(site.status)}
          </div>
          <div class="net">${fmt(site.network_prefix)}</div>
        </div>
        <div class="counts">
          <div>SSH open hosts: <strong>${site.ssh_open_hosts}</strong></div>
          <div>Aruba switches: <strong>${site.aruba_count}</strong></div>
          <div>Reachable: <strong>${site.reachable_count}</strong></div>
          <div>Up interfaces: <strong>${site.up_interface_total}</strong></div>
          <div>Candidates probed: <strong>${site.candidates_probed}</strong></div>
        </div>
        ${message}
        ${renderSwitchRows(site.switches)}
      </article>`;
    })
    .join("");
}

function renderMeta(data) {
  const when = data.generated_at
    ? new Date(data.generated_at).toLocaleString("en-US", { timeZone: "America/New_York" })
    : "—";
  document.getElementById("scan-meta").innerHTML = `
    Vendor: <strong>${fmt(data.vendor)}</strong><br />
    Generated: ${when} ET<br />
    Profiles: ${(data.credentials_profiles || []).join(", ") || "—"}
  `;
  document.getElementById("footer-stamp").textContent = `Scan ${when} ET`;
}

async function main() {
  try {
    const data = await loadInventory();
    renderMeta(data);
    renderTotals(data);
    renderSites(data);
  } catch (err) {
    document.getElementById("scan-meta").textContent = String(err);
    document.getElementById("sites").innerHTML =
      '<p class="message">Run <code>python3 scan/aruba_scan.py</code> to generate inventory data.</p>';
  }
}

main();
