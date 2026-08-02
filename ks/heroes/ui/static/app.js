/* Shared UI helpers loaded by _layout.html on every page.
 *
 * Kept inside an IIFE that only publishes window.showToast: the inventory
 * gear/heroes pages still declare their own top-level `const toast` in an
 * inline script, and a second top-level `const` of the same name in another
 * classic script would be a redeclaration SyntaxError. Those two pages also
 * still declare their own showToast (Task 5 migrates them); a function
 * declaration in a later script simply wins, so loading this first is safe.
 */
(function () {
  "use strict";

  var OK_MS = 2500;
  var ERR_MS = 6000; // errors carry a message worth reading — linger longer
  var timer = null;

  /**
   * Show a message in the #toast live region.
   * @param {string} message text to announce
   * @param {boolean} ok true for the success style, false for the error style
   */
  function showToast(message, ok) {
    var el = document.getElementById("toast");
    if (!el) return;
    el.className = ok ? "ok" : "err";
    // Un-hide *before* writing the text: screen readers routinely miss
    // mutations made to a display:none live region. `hidden` is toggled as a
    // property alongside the class so role="status" behaves consistently.
    el.hidden = false;
    el.textContent = String(message);
    clearTimeout(timer);
    timer = setTimeout(function () {
      el.className = "";
      el.hidden = true;
      el.textContent = "";
    }, ok ? OK_MS : ERR_MS);
  }

  window.showToast = showToast;
})();
