import { createRoot } from 'react-dom/client';
import AccountApp from '../../src/features/accounts/AccountApp';
import AlertsButton from '../../src/components/AlertsButton';
import '../../src/styles/globals.css';
import '../../src/styles/account-reference.css';
import '../../src/styles/account-flow.css';
import '../../src/styles/accounts.css';
createRoot(document.getElementById('root')!).render(new URLSearchParams(location.search).has('header')
  ? <AlertsButton />
  : <AccountApp publishableKey="FIXTURE_ONLY" initial={new URLSearchParams(location.search).get('initial') ?? 'alerts'} />);
