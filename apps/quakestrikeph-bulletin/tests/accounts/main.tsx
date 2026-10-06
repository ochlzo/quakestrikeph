import { createRoot } from 'react-dom/client';
import './resume-fixture';
import './channels-fixture';
import AccountApp from '../../src/features/accounts/AccountApp';
import AlertsButton from '../../src/components/AlertsButton';
import './styles.css';
import '../../src/styles/account-reference.css';
import '../../src/styles/account-flow.css';
import '../../src/styles/accounts.css';
createRoot(document.getElementById('root')!).render(new URLSearchParams(location.search).has('header')
  ? <AlertsButton />
  : <AccountApp publishableKey="FIXTURE_ONLY" initial={new URLSearchParams(location.search).get('initial') ?? 'alerts'} />);
