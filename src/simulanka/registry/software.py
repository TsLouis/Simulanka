"""Non-research example package used to prove Registry v2 extension closure."""

from simulanka.registry.profiles import (
    CapabilitySpec,
    EdgeProfileSpec,
    NodeProfileSpec,
    PresentationSpec,
    RegistryPackage,
    TemplatePortSpec,
    TemplateSpec,
)

SOFTWARE_SERVICE_PACKAGE = RegistryPackage(
    name="software-service-example",
    capabilities=(
        CapabilitySpec(
            key="deployable",
            consumers=frozenset({"action", "presentation"}),
            description="May expose deployment actions and deployment state.",
        ),
    ),
    node_profiles=(
        NodeProfileSpec(
            key="software.service",
            capabilities=frozenset(
                {"contextualizable", "renamable", "deletable", "deployable"}
            ),
            allow_parents=frozenset({"directory"}),
            attrs_fields={"runtime": "string", "endpoint": "string"},
            presentation="software.service",
            tags=frozenset({"software"}),
        ),
    ),
    edge_profiles=(
        EdgeProfileSpec(
            key="software.depends_on",
            needs_ports=False,
            source_profiles=frozenset({"software.service"}),
            target_profiles=frozenset({"software.service"}),
            tags=frozenset({"software"}),
        ),
    ),
    presentations=(
        PresentationSpec(
            key="software.service",
            category="Software",
            palette_token="service",
            icon="server",
            card_fields=("runtime", "endpoint"),
            inspector_fields=("runtime", "endpoint"),
            badges=("deployable",),
        ),
    ),
    templates=(
        TemplateSpec(
            key="software.http-service",
            profile="software.service",
            name="HTTP Service",
            category="Software",
            default_attrs={"runtime": "python", "endpoint": "/health"},
            default_ports=(
                TemplatePortSpec(name="in", direction="in", port_type="any"),
                TemplatePortSpec(name="out", direction="out", port_type="any"),
            ),
        ),
    ),
)
