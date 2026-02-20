import type { Metadata } from "next";
import "./globals.css";
import { Providers } from "./providers";

export const metadata: Metadata = {
  title: "BitBot Dashboard",
  description: "Crypto dip-buying trading agent monitor",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-zinc-950 text-zinc-100 antialiased">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
