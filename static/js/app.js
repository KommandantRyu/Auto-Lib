(() => {
  // Password show/hide toggles
  document.querySelectorAll("[data-toggle-password]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const id = btn.getAttribute("data-toggle-password");
      if (!id) return;
      const input = document.getElementById(id);
      if (!input) return;
      input.type = input.type === "password" ? "text" : "password";
      const pressed = btn.getAttribute("aria-pressed") === "true";
      btn.setAttribute("aria-pressed", String(!pressed));
    });
  });

  // Sidebar active state (based on body[data-page] + nav-item[data-page])
  const page = document.body?.getAttribute("data-page");
  if (page) {
    document.querySelectorAll(".nav-item[data-page]").forEach((a) => {
      if (a.getAttribute("data-page") === page) a.classList.add("active");
    });
  }

  // Checkout tabs (dashboard demo)
  document.querySelectorAll("[data-checkout-tab]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const key = btn.getAttribute("data-checkout-tab");
      if (!key) return;

      document.querySelectorAll("[data-checkout-tab]").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");

      document.querySelectorAll("[data-checkout-table]").forEach((table) => {
        table.style.display = table.getAttribute("data-checkout-table") === key ? "" : "none";
      });
    });
  });

  // Members filter (demo)
  document.querySelectorAll("[data-members-filter]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const filter = btn.getAttribute("data-members-filter");
      if (!filter) return;

      document.querySelectorAll("[data-members-filter]").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");

      document.querySelectorAll("tr[data-member-status]").forEach((row) => {
        const status = row.getAttribute("data-member-status");
        row.style.display = filter === "all" || status === filter ? "" : "none";
      });
    });
  });
})();

