// Show / Hide button on password fields.
document.querySelectorAll("[data-toggle-password]").forEach(function (button) {
  button.addEventListener("click", function () {
    var input = document.getElementById(button.dataset.togglePassword);
    var showing = input.type === "text";
    input.type = showing ? "password" : "text";
    button.textContent = showing ? "Show" : "Hide";
  });
});

// Ask "Are you sure?" before anything marked data-confirm is submitted (like Delete).
document.querySelectorAll("form[data-confirm]").forEach(function (form) {
  form.addEventListener("submit", function (event) {
    if (!window.confirm(form.dataset.confirm)) {
      event.preventDefault();
    }
  });
});

// New transactions start on today's date on YOUR device, not the server's.
document.querySelectorAll("input[data-default-today]").forEach(function (input) {
  var now = new Date();
  var month = String(now.getMonth() + 1).padStart(2, "0");
  var day = String(now.getDate()).padStart(2, "0");
  input.value = now.getFullYear() + "-" + month + "-" + day;
});

// If a form comes back with a mistake, bring the first one into view (helpful on phones).
var firstError = document.querySelector(".field--error");
if (firstError) {
  firstError.scrollIntoView({ block: "center" });
}
