import tseslint from "typescript-eslint";

export default tseslint.config(
  { ignores: ["coverage", "miniprogram_npm"] },
  ...tseslint.configs.recommended,
);
