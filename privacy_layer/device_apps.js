// Fixed JavaScript for Automation program. Private arguments arrive over stdin.
ObjC.import('Foundation');

function run(argv) {
  const input = $.NSFileHandle.fileHandleWithStandardInput.readDataToEndOfFile;
  const data = JSON.parse(ObjC.unwrap($.NSString.alloc.initWithDataEncoding(input, $.NSUTF8StringEncoding)));
  const operation = argv[0];

  if (operation === 'mail') {
    const selected = Application('Mail').selection().slice(0, 1);
    return JSON.stringify(selected.map(message => ({title: message.subject(), recipient: message.sender()})));
  }
  if (operation === 'email') {
    const mail = Application('Mail');
    const message = mail.OutgoingMessage({subject: data.subject, content: data.body, visible: false});
    mail.outgoingMessages.push(message);
    data.recipients.forEach(address => message.toRecipients.push(mail.Recipient({address})));
    if (data.attachmentPath) {
      message.attachments.push(mail.Attachment({fileName: data.attachmentPath}));
      const expected = data.attachmentPath.split('/').pop();
      let ready = false;
      for (let i = 0; i < 25; i++) {
        if (message.attachments.name().includes(expected)) { ready = true; break; }
        delay(0.2);
      }
      if (!ready) throw new Error('Mail did not confirm the attachment.');
    }
    if (!message.send()) throw new Error('Mail did not confirm submission.');
    return 'true';
  }
  const calendar = Application('Calendar');
  if (operation === 'calendar') {
    const now = new Date();
    const earliest = new Date(now.getTime() - 7 * 86400000);
    const meetings = [];
    for (const book of calendar.calendars()) {
      const events = book.events.whose({_and: [{startDate: {_greaterThan: earliest}}, {startDate: {_lessThan: now}}]})();
      for (const event of events.slice(-40)) {
        const recipients = event.attendees.email().filter(Boolean);
        if (recipients.length) meetings.push({title: event.summary(), recipients, when: event.startDate().getTime()});
      }
    }
    return JSON.stringify(meetings.sort((a, b) => b.when - a.when).slice(0, 15));
  }
  if (operation === 'event') {
    const book = calendar.calendars.whose({name: data.calendar, writable: true})();
    if (book.length !== 1) throw new Error('Choose one uniquely named writable calendar.');
    const event = calendar.Event({summary: data.title, startDate: new Date(data.start), endDate: new Date(data.end)});
    book[0].events.push(event);
    return 'true';
  }
  throw new Error('Unknown action.');
}
