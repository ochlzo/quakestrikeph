import { Toaster } from './ui/toast';
import { useState } from 'react';
export default function BackgroundToaster() {
  const [container, setContainer] = useState<HTMLDivElement | null>(null);
  return <div ref={setContainer}>{container && <Toaster portalContainer={container} />}</div>;
}
