import { Figtree } from 'next/font/google';
import localFont from 'next/font/local';

export const figtreeFont = Figtree({ subsets: ['latin'], variable: '--font-figtree' });
export const nasalizationFont = localFont({
  src: '../public/font/nasalization/nasalization-rg.otf',
  variable: '--font-nasalization',
});
