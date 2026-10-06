// Mengurai teks menu akun Tuton jadi nama dan NIM. Dipakai proses utama untuk chip akun di header Asisten.
// Jalankan `node tuton-account.js` untuk cek mandiri.

// Menu akun Tuton menulis nama kapital diikuti NIM, misalnya "CITRA NUR ANNISSA 058215934"
function parseUsertext(raw) {
  const text = String(raw || "").replace(/<[^>]*>/g, " ").replace(/&amp;/g, "&").replace(/&#0?39;|&apos;/g, "'").replace(/\s+/g, " ").trim().slice(0, 140);
  if (!text) return { loggedIn: false, name: "", nim: "" };
  const match = text.match(/^(.*?)\s*(\d{8,10})$/);
  const name = (match ? match[1] : text).toLowerCase().replace(/(^|[\s'-])\p{L}/gu, (c) => c.toUpperCase());
  return { loggedIn: true, name: name.slice(0, 100), nim: match ? match[2] : "" };
}

// Halaman dasbor Moodle yang sudah login punya span menu akun. Halaman login tidak punya.
function parseDashboard(html) {
  const match = String(html || "").match(/class="[^"]*\busertext\b[^"]*"[^>]*>([\s\S]*?)<\/span>/);
  return parseUsertext(match ? match[1] : "");
}

module.exports = { parseUsertext, parseDashboard };

if (require.main === module) {
  const assert = require("node:assert");
  assert.deepStrictEqual(parseUsertext("CITRA NUR ANNISSA 058215934"), { loggedIn: true, name: "Citra Nur Annissa", nim: "058215934" });
  assert.deepStrictEqual(parseUsertext(" <b>RAHMA O&#039;NEIL</b> 048127356 "), { loggedIn: true, name: "Rahma O'Neil", nim: "048127356" });
  assert.deepStrictEqual(parseUsertext(""), { loggedIn: false, name: "", nim: "" });
  assert.strictEqual(parseDashboard('<span class="usertext mr-1">BUDI SANTOSO 041234567</span>').nim, "041234567");
  assert.strictEqual(parseDashboard('<form id="login">Masuk</form>').loggedIn, false);
  console.log("tuton-account ok");
}
