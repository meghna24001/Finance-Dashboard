// Draws the two charts on the Home page.
// The numbers come from the page itself (the <script id="chart-data"> block).
(function () {
  var dataElement = document.getElementById("chart-data");
  if (!dataElement || typeof Chart === "undefined") {
    return; // The lists and the table on the page still show every figure.
  }
  var data = JSON.parse(dataElement.textContent);

  // Format numbers as money in the person's currency, e.g. ₹1,00,000.00
  function money(value, compact) {
    var options = { style: "currency", currency: data.currency };
    if (compact) {
      options.notation = "compact";
    }
    try {
      return new Intl.NumberFormat(data.locale, options).format(value);
    } catch (error) {
      return new Intl.NumberFormat("en", options).format(value);
    }
  }

  var ink = "#1b2b34";
  var muted = "#5b6b72";
  var gridLine = "#e1e8e5";
  var groupedIncome = "#f783ac";
  var groupedSpent = "#7ea6d8";

  Chart.defaults.font.family = 'system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif';
  Chart.defaults.font.size = 13;
  Chart.defaults.color = muted;
  if (window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
    Chart.defaults.animation = false;
  }

  // ---- Where your money went (doughnut)
  var spendingCanvas = document.getElementById("spending-chart");
  if (spendingCanvas && data.spending.values.length) {
    new Chart(spendingCanvas, {
      type: "doughnut",
      data: {
        labels: data.spending.labels,
        datasets: [{
          data: data.spending.values,
          backgroundColor: data.spending.colors,
          borderColor: "#ffffff",
          borderWidth: 2
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        cutout: "62%",
        plugins: {
          legend: { display: false }, // the list beside the chart is the legend
          tooltip: {
            callbacks: {
              label: function (context) {
                return " " + context.label + ": " + money(context.parsed);
              }
            }
          }
        }
      }
    });
  }

  // ---- Last 6 months (grouped bars: Income and Spent touch within each month)
  var trendCanvas = document.getElementById("trend-chart");
  if (trendCanvas) {
    new Chart(trendCanvas, {
      type: "bar",
      data: {
        labels: data.trend.labels,
        datasets: [
          {
            label: "Income",
            data: data.trend.income,
            backgroundColor: groupedIncome,
            borderColor: "#db6f98",
            borderWidth: 1,
            borderRadius: 0,
            categoryPercentage: 0.7,
            barPercentage: 1,
            maxBarThickness: 34
          },
          {
            label: "Spent",
            data: data.trend.spent,
            backgroundColor: groupedSpent,
            borderColor: "#668fbe",
            borderWidth: 1,
            borderRadius: 0,
            categoryPercentage: 0.7,
            barPercentage: 1,
            maxBarThickness: 34
          }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        scales: {
          x: { grid: { display: false }, border: { color: gridLine } },
          y: {
            beginAtZero: true,
            grid: { color: gridLine },
            border: { display: false },
            ticks: {
              maxTicksLimit: 5,
              callback: function (value) { return money(value, true); }
            }
          }
        },
        plugins: {
          legend: { position: "top", align: "start", labels: { boxWidth: 12, boxHeight: 12, color: ink } },
          tooltip: {
            callbacks: {
              title: function (items) { return data.trend.titles[items[0].dataIndex]; },
              label: function (context) { return " " + context.dataset.label + ": " + money(context.parsed.y); }
            }
          }
        }
      }
    });
  }
})();
