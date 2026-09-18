# Teams discussions

Internal application groups and their membership controls remain available independently of Microsoft Teams.

On an answer, choose **Discuss in Microsoft Teams**. The backend authorizes the meeting, resolves actual attendance identities and inspects chats accessible to the signed-in user. Exact membership matching selects an existing chat. Otherwise, select resolved participants and confirm group creation. The signed-in user is included. Creating the chat does not send a message; sending the saved answer and its references requires a separate confirmation.

Historical document names do not identify Entra users. Unresolved identities are displayed honestly and cannot be selected. Missing configuration, consent, encrypted token storage or Graph access leaves the rest of the application operational. No simulated Teams chat or successful send is returned.

See MICROSOFT_GRAPH_PERMISSIONS.md for configuration, least-privilege permissions and deployment validation. Tests use mocked Graph responses; real tenant consent and delivery are not verified by local tests.
