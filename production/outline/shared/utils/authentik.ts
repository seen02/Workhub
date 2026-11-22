/**
 * Builds the password change entry URL from an Authentik OIDC endpoint.
 * Preserves reverse proxy prefixes such as `/authentik/`.
 *
 * @param oidcUrl the configured issuer or authorization endpoint.
 * @param outlineUrl the configured public Outline URL.
 * @returns the flow URL, or undefined if the configuration is unsupported.
 */
export function getAuthentikPasswordChangeUrl(
  oidcUrl: string | undefined,
  outlineUrl: string | undefined
): string | undefined {
  if (!oidcUrl || !outlineUrl) {
    return undefined;
  }

  try {
    const url = new URL(oidcUrl);
    const returnUrl = new URL("/settings", outlineUrl);
    const match = url.pathname.match(/^(.*)\/application\/o\/([^/]+)\/?$/);

    if (
      !match ||
      !["http:", "https:"].includes(url.protocol) ||
      !["http:", "https:"].includes(returnUrl.protocol) ||
      url.username ||
      url.password ||
      returnUrl.username ||
      returnUrl.password
    ) {
      return undefined;
    }

    url.pathname = `${match[1]}/if/flow/default-password-change/`;
    url.search = "";
    url.hash = "";
    // Authentik only accepts relative `next` URLs. Its application launcher
    // handles the return to Outline when Authentik uses a separate origin.
    const next =
      url.origin === returnUrl.origin
        ? returnUrl.pathname
        : match[2] !== "authorize"
          ? `${match[1]}/application/launch/${match[2]}/`
          : `${match[1]}/if/user/`;
    url.searchParams.set("next", next);

    // Verify identity using the configured authentication flow before changing
    // the password, including when the previous SSO session has expired.
    const entry = new URL(`${match[1]}/flows/-/default/authentication/`, url);
    entry.searchParams.set("next", url.pathname + url.search);
    return entry.toString();
  } catch {
    return undefined;
  }
}
