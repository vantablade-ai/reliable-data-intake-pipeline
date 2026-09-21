from .base import ProviderAdapter, ProviderCandidate
from .provider_alpha import ProviderAlphaAdapter
from .provider_beta import ProviderBetaAdapter
from .provider_gamma import ProviderGammaAdapter


ADAPTERS: dict[str, ProviderAdapter] = {
    "provider_alpha": ProviderAlphaAdapter(),
    "provider_beta": ProviderBetaAdapter(),
    "provider_gamma": ProviderGammaAdapter(),
}


def adapter_for(provider: str) -> ProviderAdapter:
    try:
        return ADAPTERS[provider.strip().lower()]
    except KeyError as exc:
        raise ValueError("unsupported provider") from exc
