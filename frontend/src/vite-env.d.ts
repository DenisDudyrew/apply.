/// <reference types="vite/client" />

interface Window {
  ApplyAndroid?: { request(path: string, body: string): string };
}
