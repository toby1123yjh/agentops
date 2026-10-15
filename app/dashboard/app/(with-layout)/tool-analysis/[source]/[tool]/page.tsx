'use client';

import { useParams } from 'next/navigation';
import { ToolAnalysis } from '../../tool-analysis';

export default function Page() {
  const params = useParams<{ source: string; tool: string }>();
  return (
    <ToolAnalysis
      source={decodeURIComponent(params.source)}
      toolKey={decodeURIComponent(params.tool)}
    />
  );
}
