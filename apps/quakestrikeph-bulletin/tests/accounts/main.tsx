import { createRoot } from 'react-dom/client';
import AccountApp from '../../src/features/accounts/AccountApp';
import '../../src/styles/globals.css';
import '../../src/styles/account-reference.css';
import '../../src/styles/account-flow.css';
import '../../src/styles/accounts.css';
createRoot(document.getElementById('root')!).render(<AccountApp publishableKey="FIXTURE_ONLY" initial={new URLSearchParams(location.search).get('initial') ?? 'alerts'} />);
