import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "TigerLite",
  description: "AI-powered ops platform.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body className="min-h-screen bg-background text-foreground antialiased">
        {children}
      </body>
    </html>
  );
}
