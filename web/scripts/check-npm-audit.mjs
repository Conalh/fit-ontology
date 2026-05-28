#!/usr/bin/env node
import { spawnSync } from "node:child_process";

const SEVERITY_RANK = new Map([
  ["info", 0],
  ["low", 1],
  ["moderate", 2],
  ["high", 3],
  ["critical", 4],
]);

const MIN_SEVERITY = "moderate";
const IGNORED_ADVISORIES = new Set([
  // Next 16.2.6 bundles postcss <8.5.10. npm audit suggests downgrading
  // Next to 9.x, which is not a valid remediation for this app.
  "GHSA-qx2v-qp2m-jg93",
]);

const audit = spawnSync("npm audit --audit-level=moderate --json", {
  encoding: "utf8",
  shell: true,
});

if (!audit.stdout) {
  process.stderr.write(audit.stderr || "npm audit produced no JSON output.\n");
  process.exit(audit.status || 1);
}

let report;
try {
  report = JSON.parse(audit.stdout);
} catch (error) {
  process.stderr.write(`Could not parse npm audit JSON: ${error.message}\n`);
  process.stderr.write(audit.stdout);
  process.exit(1);
}

const vulnerabilities = report.vulnerabilities ?? {};
const ignoredPackages = new Set();

function advisoryIds(vulnerability) {
  return (vulnerability.via ?? [])
    .filter((via) => typeof via === "object" && via.url)
    .map((via) => via.url.split("/").pop());
}

function isAtLeastSeverity(severity, minimum) {
  return (SEVERITY_RANK.get(severity) ?? 0) >= (SEVERITY_RANK.get(minimum) ?? 0);
}

let changed = true;
while (changed) {
  changed = false;
  for (const [name, vulnerability] of Object.entries(vulnerabilities)) {
    if (ignoredPackages.has(name)) continue;
    const directIds = advisoryIds(vulnerability);
    const directIgnored = directIds.length > 0 && directIds.every((id) => IGNORED_ADVISORIES.has(id));
    const transitiveIgnored = (vulnerability.via ?? [])
      .filter((via) => typeof via === "string")
      .every((via) => ignoredPackages.has(via));
    const hasTransitiveVia = (vulnerability.via ?? []).some((via) => typeof via === "string");
    if (directIgnored || (hasTransitiveVia && transitiveIgnored && directIds.length === 0)) {
      ignoredPackages.add(name);
      changed = true;
    }
  }
}

const failures = Object.entries(vulnerabilities).filter(([name, vulnerability]) => {
  return !ignoredPackages.has(name) && isAtLeastSeverity(vulnerability.severity, MIN_SEVERITY);
});

if (failures.length > 0) {
  for (const [name, vulnerability] of failures) {
    process.stderr.write(`${name}: ${vulnerability.severity} ${vulnerability.range ?? ""}\n`);
  }
  process.exit(1);
}

const ignored = [...ignoredPackages].sort().join(", ") || "none";
process.stdout.write(`npm audit clean for new ${MIN_SEVERITY}+ advisories; ignored: ${ignored}\n`);
