import { getAuthentikPasswordChangeUrl } from "./authentik";

describe("getAuthentikPasswordChangeUrl", () => {
  it("uses the separate Authentik domain for local testing", () => {
    const url = new URL(
      getAuthentikPasswordChangeUrl(
        "http://authentik.workhub.test/application/o/outline/",
        "http://outline.workhub.test"
      ) ?? ""
    );
    expect(url.origin).toBe("http://authentik.workhub.test");
    expect(url.pathname).toBe("/flows/-/default/authentication/");
    const flow = new URL(url.searchParams.get("next") ?? "", url);
    expect(flow.pathname).toBe("/if/flow/default-password-change/");
    expect(flow.searchParams.get("next")).toBe("/application/launch/outline/");
  });

  it("preserves the VM public port and Authentik proxy prefix", () => {
    const url = new URL(
      getAuthentikPasswordChangeUrl(
        "https://pms.example.com:21801/authentik/application/o/outline/",
        "https://pms.example.com:21801"
      ) ?? ""
    );
    expect(url.origin).toBe("https://pms.example.com:21801");
    expect(url.pathname).toBe("/authentik/flows/-/default/authentication/");
    const flow = new URL(url.searchParams.get("next") ?? "", url);
    expect(flow.pathname).toBe("/authentik/if/flow/default-password-change/");
    expect(flow.searchParams.get("next")).toBe("/settings");
  });

  it("supports manual authorization endpoints without forwarding their query", () => {
    const url = new URL(
      getAuthentikPasswordChangeUrl(
        "http://auth.example.com/authentik/application/o/authorize/?prompt=login#old",
        "http://outline.example.com"
      ) ?? ""
    );
    expect(url.pathname).toBe("/authentik/flows/-/default/authentication/");
    const flow = new URL(url.searchParams.get("next") ?? "", url);
    expect(flow.pathname).toBe("/authentik/if/flow/default-password-change/");
    expect(flow.searchParams.get("next")).toBe("/authentik/if/user/");
    expect(flow.searchParams.has("prompt")).toBe(false);
    expect(url.hash).toBe("");
  });

  it.each([
    [undefined, "http://outline.example.com"],
    ["http://auth.example.com/application/o/outline/", undefined],
    ["invalid", "http://outline.example.com"],
    [
      "https://other.example.com/oauth2/authorize",
      "http://outline.example.com",
    ],
    ["javascript:alert(1)", "http://outline.example.com"],
    [
      "ftp://auth.example.com/application/o/outline/",
      "http://outline.example.com",
    ],
    ["http://auth.example.com/application/o/outline/", "javascript:alert(1)"],
    [
      "http://user:secret@auth.example.com/application/o/outline/",
      "http://outline.example.com",
    ],
  ])("hides the action for unsupported configuration (%s)", (oidc, outline) => {
    expect(getAuthentikPasswordChangeUrl(oidc, outline)).toBeUndefined();
  });
});
