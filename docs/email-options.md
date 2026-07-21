# Email on `@tommasofrancescon.it`

Email uses DNS MX records to decide who receives messages for the domain. It is
separate from the web server and should not be added to this Docker stack by
default. Your normal Gmail address can continue to exist unchanged while you
add an address such as `ciao@tommasofrancescon.it`.

## Practical choices

| Choice | Cost | What it provides | Main trade-off |
| --- | --- | --- | --- |
| Cloudflare Email Routing to Gmail | Free for incoming aliases | `name@domain` forwards into the Gmail inbox you already use | It is not a mailbox and cannot send reliably as the domain without an external SMTP service |
| Managed mailbox (Google Workspace, Proton Mail, Fastmail, etc.) | Monthly fee | Mailbox, sending reputation, spam filtering, DKIM/SPF help and support | Ongoing cost |
| Full self-hosted mail server | Software may be free | Maximum control and a real mailbox at home | A static IP/PTR, port 25 reachability, spam reputation, DKIM/SPF/DMARC, patching and monitoring are your responsibility |

## Why a mail server at home is difficult

Receiving mail is only one part. Large providers often reject or spam-folder
messages from residential connections because the IP is dynamic, port 25 may be
blocked, and the provider cannot set a matching reverse-DNS (PTR) record.
Temporary forwarding to Gmail during downtime does not solve the sender
reputation problem, and switching MX records back and forth can delay or lose
mail while DNS changes propagate.

A full self-hosted system needs a stable public IP, working inbound TCP/25,
forward and reverse DNS that match, TLS, SPF, DKIM, DMARC, backups, monitoring,
and a process for IP blocklists. It is a worthwhile learning project on a
separate host, but not a good dependency for password resets or important
personal mail.

## Recommended starting point

Use Cloudflare Email Routing for one or more inbound aliases that forward to
your existing Gmail inbox. When sending is needed, choose a reputable SMTP
provider or a managed mailbox; then add only the MX/SPF/DKIM records that
provider specifies. Mail DNS records must be **DNS only**, never orange-cloud
proxied.

Before changing anything, decide whether old Aruba-hosted mail must keep
working. Once Cloudflare is authoritative, copy the current MX and any related
SPF/DKIM/DMARC records to Cloudflare only if they belong to a service you intend
to keep. Aruba's old DNS panel no longer controls live answers after the
Cloudflare nameserver switch.

Useful provider documentation: [Cloudflare email DNS records](https://developers.cloudflare.com/dns/manage-dns-records/how-to/email-records/) and [Google Workspace MX setup](https://support.google.com/a/answer/6156494).
