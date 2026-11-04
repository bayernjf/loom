import { FlatCompat } from '@eslint/eslintrc'

// P3-4：最小可跑配置——官方 next 规则集，不额外叠自定义规则。
const compat = new FlatCompat({ baseDirectory: import.meta.dirname })

const config = [
  {
    ignores: ['.next/**', 'node_modules/**', 'next-env.d.ts', '**/*.tsbuildinfo'],
  },
  ...compat.extends('next/core-web-vitals', 'next/typescript'),
]

export default config
