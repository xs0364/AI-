import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";
import { ThemeProvider } from "@/components/theme-provider";
import { TopBar } from "@/components/top-bar";
import { LeftSidebar } from "@/components/left-sidebar";
import { RightPanel } from "@/components/right-panel";
import { Toaster } from "@/components/ui/sonner";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Quant Dashboard — 量化交易系统",
  description: "模拟基金量化交易系统",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="zh-CN"
      suppressHydrationWarning
      className={`${geistSans.variable} ${geistMono.variable}`}
    >
      <body className="h-screen overflow-hidden bg-surface-0 text-text-primary">
        <ThemeProvider>
          {/* 四面板布局 */}
          <div className="flex flex-col h-full">
            <TopBar />
            <div className="flex flex-1 min-h-0">
              <LeftSidebar />
              <main className="flex-1 min-w-0 overflow-auto p-4">
                {children}
              </main>
              <RightPanel />
            </div>
          </div>
          <Toaster />
        </ThemeProvider>
      </body>
    </html>
  );
}
