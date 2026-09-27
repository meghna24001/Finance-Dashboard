(function () {
  var selectAll = document.querySelector('[data-import-select-all]');
  if (!selectAll) return;
  var rows = document.querySelectorAll('[data-import-row]');
  selectAll.addEventListener('change', function () {
    rows.forEach(function (row) { row.checked = selectAll.checked; });
  });
  rows.forEach(function (row) {
    row.addEventListener('change', function () {
      selectAll.checked = Array.prototype.every.call(rows, function (item) { return item.checked; });
    });
  });
})();
