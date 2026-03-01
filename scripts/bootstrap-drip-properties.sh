#!/bin/bash
# Bootstrap drip_subject and drip_body as Loops contact properties.
# Run once: doppler run -- sh scripts/bootstrap-drip-properties.sh

set -e

echo "Bootstrapping drip properties in Loops..."

curl -s -X PUT "https://app.loops.so/api/v1/contacts/update" \
  -H "Authorization: Bearer $LOOPS_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "email": "test-drip-bootstrap@synter-internal.com",
    "firstName": "Test",
    "lastName": "Drip",
    "source": "drip-bootstrap",
    "subscribed": false,
    "drip_subject": "test subject",
    "drip_body": "test body"
  }' | python3 -m json.tool

echo ""
echo "Cleaning up bootstrap contact..."

curl -s -X POST "https://app.loops.so/api/v1/contacts/delete" \
  -H "Authorization: Bearer $LOOPS_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"email": "test-drip-bootstrap@synter-internal.com"}' | python3 -m json.tool

echo ""
echo "Done! drip_subject and drip_body properties are now available in Loops."
echo ""
echo "Next: Create ONE Loop automation in Loops UI:"
echo "  1. Go to Loops → Loops → Create Loop"
echo "  2. Trigger: Event received → drip_email"
echo "  3. Add Email step:"
echo "     - Subject: {{drip_subject}}"
echo "     - Body: {{drip_body}}"
echo "     - From: joel@mail.syntermedia.ai"
echo "     - Reply-to: joel@syntermedia.ai"
echo "  4. Activate the Loop"
