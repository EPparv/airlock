'use strict';
let onboardingStarted=false,gmailTimer=null,gmailDeadline=0;
function renderOnboarding(){
 if(!dashboard)return;
 if(dashboard.demo_only){$('onboarding').hidden=true;return;}
 const hasContext=dashboard.counts.memories+dashboard.counts.skills>0;
 const hasMail=!!dashboard.gmail.account;
 const connections=dashboard.connections.filter(active);
 const mailAvailable=dashboard.gmail.configured||hasMail;
 const skipped=dashboard.onboarding?.gmail_skipped===true||!mailAvailable;
 const needsSetup=!hasContext||(!hasMail&&!skipped)||!connections.length;
 const visible=!dashboard.onboarding?.dismissed&&(onboardingStarted||needsSetup);
 onboardingStarted=visible;
 $('onboarding').hidden=!visible;
 $('overviewHeading').hidden=visible;
 $('overviewContent').hidden=visible;
 $('resumeSetup').hidden=visible;
 const complete=[hasContext,hasMail||skipped,!!connections.length];
 for(let i=0;i<3;i++){
  const card=$('setupStep'+(i+1));card.classList.toggle('complete',complete[i]);card.classList.toggle('current',i===complete.indexOf(false));
  card.querySelector('.step-number').textContent=complete[i]?'✓':String(i+1);
 }
 $('setupProgress').textContent=`${complete.filter(Boolean).length} of 3 steps ready`;
 $('setupContextStatus').textContent=hasContext?`${dashboard.counts.memories} memories · ${dashboard.counts.skills} skills added`:'Facts about you, and how you like things done.';
 $('setupImport').textContent=hasContext?'Add more context':'Import memories & skills';
 $('setupGmailStatus').textContent=hasMail?'Your Gmail is connected. Read-only access.':skipped?'Skipped for now. You can connect anytime.':'Sign in with Google. No email is sent or changed.';
 $('setupGmail').textContent=hasMail?'Reconnect Gmail':'Connect Gmail';
 $('setupSkipGmail').hidden=hasMail||skipped;
 $('reconnect').textContent=hasMail?'Reconnect':'Connect Gmail';
 $('setupGmail').disabled=!mailAvailable;
 $('reconnect').disabled=!mailAvailable;
 $('checkGmail').disabled=!hasMail;
 if(!mailAvailable)$('setupGmailStatus').textContent='Gmail sign-in is not configured in this public build. Continue to connect your AI; imported context works normally.';
 $('setupAgentStatus').textContent=connections.length?connections.some(x=>x.used)?'Your AI has successfully used this connection.':'Settings saved. Restart your AI, then try the prompt below.':'Choose the AI app you already use on this Mac.';
 $('setupTry').hidden=!connections.length;
 $('finishSetup').hidden=!complete.every(Boolean);
 $('setupReadyTitle').textContent=connections.some(x=>x.used)?'Your AI is using your context.':'One last step: try it in your AI.';
 $('setupReadyText').textContent=connections.some(x=>x.used)?'You can see the filtered context in Privacy → What was shared.':'Restart your AI app. Enable Airlock if it asks, then paste this prompt into a new chat.';
 $('setupQuestion').textContent=prompt;
 $('setupAi').textContent=connections.length?'Connect another AI':'Connect my AI';
 $('contextDoneNote').textContent=connections.length?'Ask your connected AI to use Airlock.':'Next, connect your AI from the setup screen. Gmail is optional.';
}
async function pollGmail(){
 clearTimeout(gmailTimer);
 if(Date.now()>gmailDeadline){notice('Google sign-in timed out. Click Connect Gmail to try again.',true);return;}
 try{
  const state=await api('gmail-state');
  if(state.sign_in==='connected'){
   await api('gmail-check');await api('onboarding',{gmail_skipped:false});await refresh();notice('Gmail connected. Choose your AI to finish setup.');return;
  }
  if(state.error){notice(state.error,true);return;}
  gmailTimer=setTimeout(pollGmail,2000);
 }catch{notice('The connection check was interrupted. Click Connect Gmail to retry.',true);}
}
async function connectGmail(){
 const popup=window.open('about:blank','_blank');if(popup)popup.opener=null;
 try{
  const result=await api('gmail-connect');
  if(popup)popup.location.href=result.url;
  else{$('gmailFallback').href=result.url;$('gmailFallback').hidden=false;}
  gmailDeadline=Date.now()+10*60*1000;notice('Finish Google sign-in in the new tab. This screen will update automatically.');pollGmail();
 }catch(error){popup?.close();throw error;}
}
$('setupImport').onclick=()=>$('addContext').click();
$('setupGmail').onclick=guard(connectGmail);
$('setupSkipGmail').onclick=guard(async()=>{await api('onboarding',{gmail_skipped:true});await refresh();});
$('setupAi').onclick=()=>{openConnect(dashboard.clients.find(c=>c.can_install&&c.app_present)?.id||'codex');$('newLifetime').value='604800';$('newCalls').value='1000';};
$('setupCopyQuestion').onclick=guard(async()=>{await navigator.clipboard.writeText(prompt);$('setupCopyQuestion').textContent='Copied';});
$('setupCheckAgent').onclick=guard(async()=>{await refresh();notice(dashboard.connections.some(x=>active(x)&&x.used)?'Your AI has used the connection successfully.':'No context request received yet. Restart your AI and paste the test prompt into a fresh chat.');});
$('finishSetup').onclick=guard(async()=>{await api('onboarding',{dismissed:true});await refresh();notice('Setup saved. Keep Airlock open while your AI uses it.');});
$('resumeSetup').onclick=guard(async()=>{await api('onboarding',{dismissed:false});onboardingStarted=true;await refresh();});
window.addEventListener('private-ai-refresh',renderOnboarding);
if(dashboard)renderOnboarding();
