// Small progressive enhancements; every page works without JavaScript.
document.addEventListener("DOMContentLoaded", () => {
  const refresh = document.getElementById("refresh-stats");
  if (refresh) {
    // On demand rather than on a timer: polling would keep an instance awake and cost money.
    refresh.addEventListener("click", async () => {
      const response = await fetch("/api/stats", { credentials: "same-origin" });
      if (!response.ok) return;
      const stats = await response.json();
      for (const [key, value] of Object.entries(stats)) {
        const cell = document.querySelector(`[data-stat="${key}"]`);
        if (cell) cell.textContent = value;
      }
      document.getElementById("refreshed").textContent = "Updated " + new Date().toLocaleTimeString();
    });
  }
  document.querySelectorAll("form[data-confirm]").forEach((form) =>
    form.addEventListener("submit", (event) => {
      if (!window.confirm(form.dataset.confirm)) event.preventDefault();
    })
  );
});
