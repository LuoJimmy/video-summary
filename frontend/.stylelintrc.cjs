/* eslint-env node */
module.exports = {
  extends: ["stylelint-config-recommended"],
  ignoreFiles: ["**/dist/**", "**/node_modules/**", "**/coverage/**"],
  rules: {
    "at-rule-no-unknown": [
      true,
      {
        ignoreAtRules: [
          "theme",
          "custom-variant",
          "utility",
          "variant",
          "plugin",
          "source",
          "reference",
          "config",
        ],
      },
    ],
    "at-rule-prelude-no-invalid": [
      true,
      {
        ignoreAtRules: ["custom-variant", "theme"],
      },
    ],
    "function-no-unknown": [
      true,
      {
        ignoreFunctions: ["theme"],
      },
    ],
    "no-descending-specificity": null,
    "property-no-vendor-prefix": true,
  },
  overrides: [
    {
      files: ["**/*.vue"],
      customSyntax: "postcss-html",
    },
  ],
};
