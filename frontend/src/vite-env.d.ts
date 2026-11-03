/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_LANGGRAPH_API_URL: string;
  readonly VITE_STUB_MODE?: string;
  readonly VITE_FIXTURE?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}

declare module "*&as=picture" {
  const value: { sources: Record<string, string>; img: { src: string; w: number; h: number } };
  export default value;
}