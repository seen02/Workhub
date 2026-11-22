/* oxlint-disable @typescript-oxlint/no-var-requires */
/* oxlint-disable no-undef */
const fs = require("node:fs");
const path = require("node:path");
const destination = path.resolve(__dirname, "build/shared/i18n/locales");
fs.mkdirSync(path.dirname(destination), { recursive: true });
fs.cpSync(path.resolve(__dirname, "shared/i18n/locales"), destination, { recursive: true });
