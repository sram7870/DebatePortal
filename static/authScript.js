document.addEventListener("DOMContentLoaded", () => {
    const emailInput = document.getElementById("email");
    const extraFields = document.getElementById("extraFields");

    emailInput.addEventListener("blur", async () => {
        const email = emailInput.value;
        if (!email.includes("@")) return;

        const response = await fetch("/auth/check_user", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ email }),
        });

        const data = await response.json();
        if (data.exists) {
            extraFields.classList.add("hidden");
        } else {
            extraFields.classList.remove("hidden");
        }
    });


});
