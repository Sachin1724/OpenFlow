#!/usr/bin/env node
// Downloads the latest OpenFlow-Setup.exe from GitHub Releases and runs it.
const https = require("https");
const fs = require("fs");
const os = require("os");
const path = require("path");
const { spawn } = require("child_process");

const URL = "https://github.com/Sachin1724/OpenFlow/releases/latest/download/OpenFlow-Setup.exe";

if (process.platform !== "win32") {
  console.error("OpenFlow is a Windows app (Windows 10/11, 64-bit).");
  process.exit(1);
}

const dest = path.join(os.tmpdir(), "OpenFlow-Setup.exe");

function get(url, hops = 0) {
  if (hops > 5) return fail("too many redirects");
  https.get(url, { headers: { "User-Agent": "openflow-npm" } }, (res) => {
    if (res.statusCode >= 300 && res.statusCode < 400 && res.headers.location) {
      res.resume();
      return get(res.headers.location, hops + 1);
    }
    if (res.statusCode !== 200) return fail("HTTP " + res.statusCode);
    const total = +res.headers["content-length"] || 0;
    let got = 0;
    res.on("data", (c) => {
      got += c.length;
      if (total) process.stdout.write(`\rDownloading OpenFlow ${Math.round((got / total) * 100)}%`);
    });
    const out = fs.createWriteStream(dest);
    res.pipe(out);
    out.on("finish", () => out.close(run));
  }).on("error", (e) => fail(e.message));
}

function run() {
  console.log("\nStarting the installer...");
  spawn(dest, [], { detached: true, stdio: "ignore" }).unref();
}

function fail(msg) {
  console.error("\nDownload failed: " + msg);
  process.exit(1);
}

console.log("Fetching the latest OpenFlow release...");
get(URL);
