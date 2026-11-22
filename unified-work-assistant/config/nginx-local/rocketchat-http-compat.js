/* Local HTTP demo only. Production deployments must use HTTPS.
 * RoomHistoryManager needs UUID v4 even when randomUUID is unavailable.
 * Keep native implementations and use the browser CSPRNG; no weak fallback.
 */
(function () {
  "use strict";
  if (location.protocol !== "http:" || location.hostname !== "rocketchat.workhub.test") return;
  var crypto = globalThis.crypto;
  if (!crypto || typeof crypto.randomUUID === "function" || typeof crypto.getRandomValues !== "function") return;
  Object.defineProperty(crypto, "randomUUID", {
    configurable: true,
    writable: true,
    value: function randomUUID() {
      var bytes = new Uint8Array(16);
      crypto.getRandomValues(bytes);
      bytes[6] = (bytes[6] & 15) | 64;
      bytes[8] = (bytes[8] & 63) | 128;
      var hex = Array.from(bytes, function (b) { return b.toString(16).padStart(2, "0"); }).join("");
      return hex.slice(0, 8) + "-" + hex.slice(8, 12) + "-" + hex.slice(12, 16) + "-" + hex.slice(16, 20) + "-" + hex.slice(20);
    }
  });
})();
