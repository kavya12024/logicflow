const form = document.querySelector("#calculator-form");
const result = document.querySelector("#result");

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  result.textContent = "Calculating...";

  const response = await fetch("/calculate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      first: Number(document.querySelector("#first").value),
      second: Number(document.querySelector("#second").value),
      operation: document.querySelector("#operation").value,
    }),
  });
  const payload = await response.json();
  result.textContent = response.ok ? payload.result : payload.error;
});