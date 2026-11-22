(async () => {
  const token = window.location.hash.slice(1);
  history.replaceState(null, "", window.location.pathname);
  const icon = document.querySelector("#icon");
  const title = document.querySelector("#title");
  const message = document.querySelector("#message");
  try {
    if (!token) throw new Error("보고 링크가 없습니다. 개인보고 방에서 새 보고를 작성해 주세요.");
    const response = await fetch("/api/review/quick-publish", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({token}),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || "보고 게시에 실패했습니다.");
    // A normal Community message can only expose a web link. After the secure
    // POST succeeds, close that link tab immediately. If the browser blocks
    // window.close(), replace it with the posted Rocket.Chat report instead of
    // leaving a separate success page behind.
    window.close();
    window.setTimeout(() => window.location.replace(result.url), 180);
  } catch (error) {
    document.body.classList.remove("processing");
    icon.textContent = "!";
    icon.classList.add("error");
    title.textContent = "보고하지 못했습니다";
    message.textContent = error.message;
  }
})();
