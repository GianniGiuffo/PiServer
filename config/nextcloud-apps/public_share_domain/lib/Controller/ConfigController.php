<?php

declare(strict_types=1);

namespace OCA\PublicShareDomain\Controller;

use OCP\AppFramework\Controller;
use OCP\AppFramework\Http\Attribute\NoAdminRequired;
use OCP\AppFramework\Http\DataResponse;
use OCP\IConfig;
use OCP\IRequest;

final class ConfigController extends Controller
{
    public function __construct(
        string $appName,
        IRequest $request,
        private IConfig $config,
    ) {
        parent::__construct($appName, $request);
    }

    #[NoAdminRequired]
    public function get(): DataResponse
    {
        return new DataResponse([
            'publicOrigin' => rtrim(
                $this->config->getSystemValueString('overwrite.cli.url'),
                '/',
            ),
        ]);
    }
}
