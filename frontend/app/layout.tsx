import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'ORCA Marine Intelligence | Autonomous Ocean Advisory',
  description:
    'Multilingual multi-agent marine intelligence, Potential Fishing Zone (PFZ) advisory, and sea safety system for Indian coastal waters (SIH26176).',
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="bg-slate-950 text-slate-100 antialiased min-h-screen">
        {children}
      </body>
    </html>
  );
}
