import type { Metadata } from 'next';
import './globals.css';
import { LivingOceanBackground } from '../components/common/LivingOceanBackground';
import { AppProvider } from '@/context/AppContext';

export const metadata: Metadata = {
  title: 'ORCA Marine Intelligence | Autonomous Ocean Advisory',
  description:
    'Multilingual multi-agent marine intelligence, Potential Fishing Zone (PFZ) advisory, and sea safety system for Indian coastal waters (SIH26176).',
};

// Default light theme (#edf6ff); respects stored `orca_theme` ("dark" | "light").
// Runs before paint to avoid a theme flash. No layout shift: background is
// fixed inset-0 pointer-events-none z-0, page content sits in a relative z-[1] wrapper.
const THEME_INIT_SCRIPT = `(function(){try{var t=localStorage.getItem('orca_theme');if(t==='dark'){document.documentElement.classList.add('dark')}else{document.documentElement.classList.remove('dark')}}catch(e){}})();`;

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_INIT_SCRIPT }} />
      </head>
      <body className="bg-[#edf6ff] text-slate-900 antialiased min-h-screen">
        <AppProvider>
          <LivingOceanBackground />
          <div className="relative z-[1]">{children}</div>
        </AppProvider>
      </body>
    </html>
  );
}
