<?php
/**
 * Elementor logistics map widget.
 *
 * @package ParsiLogisticsMap
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

use Elementor\Controls_Manager;
use Elementor\Group_Control_Background;
use Elementor\Group_Control_Border;
use Elementor\Group_Control_Box_Shadow;
use Elementor\Group_Control_Typography;
use Elementor\Icons_Manager;
use Elementor\Repeater;
use Elementor\Widget_Base;

/**
 * Editable Persian logistics map widget.
 */
class PLM_Logistics_Widget extends Widget_Base {

	/** @return string */
	public function get_name() {
		return 'plm-logistics-map';
	}

	/** @return string */
	public function get_title() {
		return esc_html__( 'نقشه لجستیک فارسی', 'parsi-logistics-map' );
	}

	/** @return string */
	public function get_icon() {
		return 'eicon-google-maps';
	}

	/** @return string[] */
	public function get_categories() {
		return array( 'general' );
	}

	/** @return string[] */
	public function get_keywords() {
		return array( 'map', 'world', 'logistics', 'service', 'نقشه', 'لجستیک', 'حمل و نقل' );
	}

	/** @return string[] */
	public function get_style_depends() {
		return array( 'parsi-logistics-map' );
	}

	/** Register all editable controls. */
	protected function register_controls() {
		$this->register_map_controls();
		$this->register_service_controls();
		$this->register_layout_style_controls();
		$this->register_map_style_controls();
		$this->register_service_style_controls();
	}

	/** Map content controls. */
	private function register_map_controls() {
		$this->start_controls_section(
			'map_content',
			array(
				'label' => esc_html__( 'نقشه و عنوان', 'parsi-logistics-map' ),
				'tab'   => Controls_Manager::TAB_CONTENT,
			)
		);

		$this->add_control(
			'map_title',
			array(
				'label'       => esc_html__( 'عنوان نقشه', 'parsi-logistics-map' ),
				'type'        => Controls_Manager::TEXT,
				'default'     => esc_html__( 'شبکه جهانی لجستیک', 'parsi-logistics-map' ),
				'label_block' => true,
			)
		);

		$this->add_control(
			'map_image',
			array(
				'label'   => esc_html__( 'تصویر نقشه', 'parsi-logistics-map' ),
				'type'    => Controls_Manager::MEDIA,
				'default' => array(
					'url' => PLM_URL . 'assets/images/blank-map-world.svg',
				),
			)
		);

		$this->add_control(
			'map_alt',
			array(
				'label'       => esc_html__( 'متن جایگزین نقشه', 'parsi-logistics-map' ),
				'type'        => Controls_Manager::TEXT,
				'default'     => esc_html__( 'نقشه شبکه جهانی حمل‌ونقل', 'parsi-logistics-map' ),
				'label_block' => true,
			)
		);

		$this->add_control(
			'show_hub',
			array(
				'label'        => esc_html__( 'نمایش نقطه مرکزی', 'parsi-logistics-map' ),
				'type'         => Controls_Manager::SWITCHER,
				'label_on'     => esc_html__( 'بله', 'parsi-logistics-map' ),
				'label_off'    => esc_html__( 'خیر', 'parsi-logistics-map' ),
				'return_value' => 'yes',
				'default'      => 'yes',
			)
		);

		$this->add_responsive_control(
			'hub_x',
			array(
				'label'      => esc_html__( 'موقعیت افقی نقطه مرکزی (%)', 'parsi-logistics-map' ),
				'type'       => Controls_Manager::SLIDER,
				'size_units' => array( '%' ),
				'range'      => array( '%' => array( 'min' => 0, 'max' => 100, 'step' => 0.1 ) ),
				'default'    => array( 'unit' => '%', 'size' => 61 ),
				'selectors'  => array( '{{WRAPPER}} .plm-map-hub' => 'left: {{SIZE}}%;' ),
				'condition'  => array( 'show_hub' => 'yes' ),
			)
		);

		$this->add_responsive_control(
			'hub_y',
			array(
				'label'      => esc_html__( 'موقعیت عمودی نقطه مرکزی (%)', 'parsi-logistics-map' ),
				'type'       => Controls_Manager::SLIDER,
				'size_units' => array( '%' ),
				'range'      => array( '%' => array( 'min' => 0, 'max' => 100, 'step' => 0.1 ) ),
				'default'    => array( 'unit' => '%', 'size' => 45 ),
				'selectors'  => array( '{{WRAPPER}} .plm-map-hub' => 'top: {{SIZE}}%;' ),
				'condition'  => array( 'show_hub' => 'yes' ),
			)
		);

		$route_repeater = new Repeater();
		$route_repeater->add_control( 'route_name', array( 'label' => esc_html__( 'نام مسیر', 'parsi-logistics-map' ), 'type' => Controls_Manager::TEXT, 'default' => esc_html__( 'مسیر جدید', 'parsi-logistics-map' ), 'label_block' => true ) );
		$route_repeater->add_control( 'start_x', array( 'label' => esc_html__( 'شروع: افقی (%)', 'parsi-logistics-map' ), 'type' => Controls_Manager::NUMBER, 'default' => 61, 'min' => 0, 'max' => 100, 'step' => 0.1 ) );
		$route_repeater->add_control( 'start_y', array( 'label' => esc_html__( 'شروع: عمودی (%)', 'parsi-logistics-map' ), 'type' => Controls_Manager::NUMBER, 'default' => 45, 'min' => 0, 'max' => 100, 'step' => 0.1 ) );
		$route_repeater->add_control( 'control_x', array( 'label' => esc_html__( 'خم مسیر: افقی (%)', 'parsi-logistics-map' ), 'type' => Controls_Manager::NUMBER, 'default' => 48, 'min' => -50, 'max' => 150, 'step' => 0.1 ) );
		$route_repeater->add_control( 'control_y', array( 'label' => esc_html__( 'خم مسیر: عمودی (%)', 'parsi-logistics-map' ), 'type' => Controls_Manager::NUMBER, 'default' => 28, 'min' => -50, 'max' => 150, 'step' => 0.1 ) );
		$route_repeater->add_control( 'end_x', array( 'label' => esc_html__( 'پایان: افقی (%)', 'parsi-logistics-map' ), 'type' => Controls_Manager::NUMBER, 'default' => 24, 'min' => 0, 'max' => 100, 'step' => 0.1 ) );
		$route_repeater->add_control( 'end_y', array( 'label' => esc_html__( 'پایان: عمودی (%)', 'parsi-logistics-map' ), 'type' => Controls_Manager::NUMBER, 'default' => 43, 'min' => 0, 'max' => 100, 'step' => 0.1 ) );
		$route_repeater->add_control( 'route_color', array( 'label' => esc_html__( 'رنگ مسیر', 'parsi-logistics-map' ), 'type' => Controls_Manager::COLOR, 'default' => '#b63b16' ) );
		$route_repeater->add_control( 'route_width', array( 'label' => esc_html__( 'ضخامت مسیر', 'parsi-logistics-map' ), 'type' => Controls_Manager::NUMBER, 'default' => 2.4, 'min' => 0.5, 'max' => 10, 'step' => 0.1 ) );
		$route_repeater->add_control( 'show_arrow', array( 'label' => esc_html__( 'نمایش پیکان', 'parsi-logistics-map' ), 'type' => Controls_Manager::SWITCHER, 'return_value' => 'yes', 'default' => 'yes' ) );

		$this->add_control(
			'routes',
			array(
				'label'       => esc_html__( 'مسیرهای حمل‌ونقل', 'parsi-logistics-map' ),
				'type'        => Controls_Manager::REPEATER,
				'fields'      => $route_repeater->get_controls(),
				'title_field' => '{{{ route_name }}}',
				'default'     => array(
					array( 'route_name' => esc_html__( 'تهران به آمریکای شمالی', 'parsi-logistics-map' ), 'start_x' => 61, 'start_y' => 45, 'control_x' => 45, 'control_y' => 22, 'end_x' => 23, 'end_y' => 42, 'route_color' => '#b63b16', 'route_width' => 2.4, 'show_arrow' => 'yes' ),
					array( 'route_name' => esc_html__( 'تهران به اروپای شمالی', 'parsi-logistics-map' ), 'start_x' => 61, 'start_y' => 45, 'control_x' => 66, 'control_y' => 28, 'end_x' => 79, 'end_y' => 31, 'route_color' => '#b63b16', 'route_width' => 2.4, 'show_arrow' => 'yes' ),
					array( 'route_name' => esc_html__( 'تهران به شرق آسیا', 'parsi-logistics-map' ), 'start_x' => 61, 'start_y' => 45, 'control_x' => 72, 'control_y' => 41, 'end_x' => 73, 'end_y' => 58, 'route_color' => '#b63b16', 'route_width' => 2.4, 'show_arrow' => 'yes' ),
					array( 'route_name' => esc_html__( 'تهران به آفریقا', 'parsi-logistics-map' ), 'start_x' => 61, 'start_y' => 45, 'control_x' => 58, 'control_y' => 57, 'end_x' => 54, 'end_y' => 66, 'route_color' => '#b63b16', 'route_width' => 2.4, 'show_arrow' => 'yes' ),
					array( 'route_name' => esc_html__( 'تهران به آمریکای جنوبی', 'parsi-logistics-map' ), 'start_x' => 61, 'start_y' => 45, 'control_x' => 50, 'control_y' => 68, 'end_x' => 34, 'end_y' => 75, 'route_color' => '#b63b16', 'route_width' => 2.4, 'show_arrow' => 'yes' ),
					array( 'route_name' => esc_html__( 'تهران به استرالیا', 'parsi-logistics-map' ), 'start_x' => 61, 'start_y' => 45, 'control_x' => 74, 'control_y' => 67, 'end_x' => 83, 'end_y' => 84, 'route_color' => '#b63b16', 'route_width' => 2.4, 'show_arrow' => 'yes' ),
				),
			)
		);

		$label_repeater = new Repeater();
		$label_repeater->add_control( 'text', array( 'label' => esc_html__( 'متن برچسب', 'parsi-logistics-map' ), 'type' => Controls_Manager::TEXT, 'default' => esc_html__( 'منطقه', 'parsi-logistics-map' ), 'label_block' => true ) );
		$label_repeater->add_control( 'x', array( 'label' => esc_html__( 'موقعیت افقی (%)', 'parsi-logistics-map' ), 'type' => Controls_Manager::NUMBER, 'default' => 50, 'min' => 0, 'max' => 100, 'step' => 0.1 ) );
		$label_repeater->add_control( 'y', array( 'label' => esc_html__( 'موقعیت عمودی (%)', 'parsi-logistics-map' ), 'type' => Controls_Manager::NUMBER, 'default' => 50, 'min' => 0, 'max' => 100, 'step' => 0.1 ) );
		$label_repeater->add_control( 'align', array( 'label' => esc_html__( 'تراز نسبت به نقطه', 'parsi-logistics-map' ), 'type' => Controls_Manager::SELECT, 'default' => 'center', 'options' => array( 'right' => esc_html__( 'راست', 'parsi-logistics-map' ), 'center' => esc_html__( 'وسط', 'parsi-logistics-map' ), 'left' => esc_html__( 'چپ', 'parsi-logistics-map' ) ) ) );

		$this->add_control(
			'map_labels',
			array(
				'label'       => esc_html__( 'برچسب‌های روی نقشه', 'parsi-logistics-map' ),
				'type'        => Controls_Manager::REPEATER,
				'fields'      => $label_repeater->get_controls(),
				'title_field' => '{{{ text }}}',
				'default'     => array(
					array( 'text' => esc_html__( 'آمریکای شمالی', 'parsi-logistics-map' ), 'x' => 10, 'y' => 56, 'align' => 'center' ),
					array( 'text' => esc_html__( 'اروپا', 'parsi-logistics-map' ), 'x' => 42, 'y' => 48, 'align' => 'center' ),
					array( 'text' => esc_html__( 'آفریقا', 'parsi-logistics-map' ), 'x' => 46, 'y' => 79, 'align' => 'center' ),
					array( 'text' => esc_html__( 'آسیا', 'parsi-logistics-map' ), 'x' => 88, 'y' => 45, 'align' => 'center' ),
					array( 'text' => esc_html__( 'استرالیا', 'parsi-logistics-map' ), 'x' => 75, 'y' => 87, 'align' => 'center' ),
				),
			)
		);

		$this->end_controls_section();
	}

	/** Service content controls. */
	private function register_service_controls() {
		$this->start_controls_section( 'services_content', array( 'label' => esc_html__( 'خدمات', 'parsi-logistics-map' ), 'tab' => Controls_Manager::TAB_CONTENT ) );
		$this->add_control( 'services_title', array( 'label' => esc_html__( 'عنوان خدمات', 'parsi-logistics-map' ), 'type' => Controls_Manager::TEXT, 'default' => esc_html__( 'خدمات ما', 'parsi-logistics-map' ), 'label_block' => true ) );
		$this->add_control( 'services_subtitle', array( 'label' => esc_html__( 'زیرعنوان', 'parsi-logistics-map' ), 'type' => Controls_Manager::TEXT, 'default' => esc_html__( 'چگونه می‌توانیم از کسب‌وکار شما پشتیبانی کنیم؟', 'parsi-logistics-map' ), 'label_block' => true ) );

		$service_repeater = new Repeater();
		$service_repeater->add_control( 'selected_icon', array( 'label' => esc_html__( 'آیکن', 'parsi-logistics-map' ), 'type' => Controls_Manager::ICONS, 'default' => array( 'value' => 'fas fa-ship', 'library' => 'fa-solid' ) ) );
		$service_repeater->add_control( 'title', array( 'label' => esc_html__( 'عنوان', 'parsi-logistics-map' ), 'type' => Controls_Manager::TEXT, 'default' => esc_html__( 'حمل‌ونقل دریایی', 'parsi-logistics-map' ), 'label_block' => true ) );
		$service_repeater->add_control( 'description', array( 'label' => esc_html__( 'توضیحات', 'parsi-logistics-map' ), 'type' => Controls_Manager::TEXTAREA, 'default' => esc_html__( 'راهکارهای اختصاصی برای حمل‌ونقل دریایی سریع، مطمئن و مقرون‌به‌صرفه.', 'parsi-logistics-map' ), 'rows' => 4 ) );
		$service_repeater->add_control( 'link', array( 'label' => esc_html__( 'پیوند کارت', 'parsi-logistics-map' ), 'type' => Controls_Manager::URL, 'placeholder' => 'https://example.com/service', 'options' => array( 'url', 'is_external', 'nofollow' ) ) );

		$this->add_control(
			'services',
			array(
				'label'       => esc_html__( 'کارت‌های خدمات', 'parsi-logistics-map' ),
				'type'        => Controls_Manager::REPEATER,
				'fields'      => $service_repeater->get_controls(),
				'title_field' => '{{{ title }}}',
				'default'     => array(
					array( 'selected_icon' => array( 'value' => 'fas fa-ship', 'library' => 'fa-solid' ), 'title' => esc_html__( 'حمل‌ونقل دریایی', 'parsi-logistics-map' ), 'description' => esc_html__( 'راهکارهای اختصاصی برای حمل دریایی کارآمد؛ از هماهنگی بار تا تحویل مطمئن در مقصدهای بین‌المللی.', 'parsi-logistics-map' ) ),
					array( 'selected_icon' => array( 'value' => 'fas fa-plane', 'library' => 'fa-solid' ), 'title' => esc_html__( 'حمل‌ونقل هوایی', 'parsi-logistics-map' ), 'description' => esc_html__( 'خدمات سریع و قابل اتکای بار هوایی برای محموله‌های زمان‌حساس، با دقت و کارایی بالا.', 'parsi-logistics-map' ) ),
				),
			)
		);
		$this->end_controls_section();
	}

	/** Overall layout and heading styles. */
	private function register_layout_style_controls() {
		$this->start_controls_section( 'layout_style', array( 'label' => esc_html__( 'چیدمان و عنوان‌ها', 'parsi-logistics-map' ), 'tab' => Controls_Manager::TAB_STYLE ) );
		$this->add_control( 'map_side', array( 'label' => esc_html__( 'جای نقشه در نمایش دسکتاپ', 'parsi-logistics-map' ), 'type' => Controls_Manager::SELECT, 'default' => 'right', 'options' => array( 'right' => esc_html__( 'سمت راست', 'parsi-logistics-map' ), 'left' => esc_html__( 'سمت چپ', 'parsi-logistics-map' ) ), 'prefix_class' => 'plm-map-side-' ) );
		$this->add_responsive_control( 'map_column_width', array( 'label' => esc_html__( 'عرض ستون نقشه (%)', 'parsi-logistics-map' ), 'type' => Controls_Manager::SLIDER, 'size_units' => array( '%' ), 'range' => array( '%' => array( 'min' => 30, 'max' => 75 ) ), 'default' => array( 'unit' => '%', 'size' => 57 ), 'tablet_default' => array( 'unit' => '%', 'size' => 54 ), 'selectors' => array( '{{WRAPPER}} .plm-map-column' => 'flex-basis: {{SIZE}}%;' ) ) );
		$this->add_responsive_control( 'columns_gap', array( 'label' => esc_html__( 'فاصله ستون‌ها', 'parsi-logistics-map' ), 'type' => Controls_Manager::SLIDER, 'size_units' => array( 'px', 'vw' ), 'range' => array( 'px' => array( 'min' => 0, 'max' => 120 ), 'vw' => array( 'min' => 0, 'max' => 10 ) ), 'default' => array( 'unit' => 'px', 'size' => 38 ), 'selectors' => array( '{{WRAPPER}} .plm-widget' => 'gap: {{SIZE}}{{UNIT}};' ) ) );
		$this->add_responsive_control( 'section_padding', array( 'label' => esc_html__( 'فاصله داخلی کل', 'parsi-logistics-map' ), 'type' => Controls_Manager::DIMENSIONS, 'size_units' => array( 'px', '%', 'em' ), 'selectors' => array( '{{WRAPPER}} .plm-widget' => 'padding: {{TOP}}{{UNIT}} {{RIGHT}}{{UNIT}} {{BOTTOM}}{{UNIT}} {{LEFT}}{{UNIT}};' ) ) );
		$this->add_control( 'map_heading_color', array( 'label' => esc_html__( 'رنگ عنوان نقشه', 'parsi-logistics-map' ), 'type' => Controls_Manager::COLOR, 'default' => '#b63b16', 'selectors' => array( '{{WRAPPER}} .plm-map-title' => 'color: {{VALUE}};' ) ) );
		$this->add_control( 'services_heading_color', array( 'label' => esc_html__( 'رنگ عنوان خدمات', 'parsi-logistics-map' ), 'type' => Controls_Manager::COLOR, 'default' => '#111111', 'selectors' => array( '{{WRAPPER}} .plm-services-title' => 'color: {{VALUE}};' ) ) );
		$this->add_group_control( Group_Control_Typography::get_type(), array( 'name' => 'heading_typography', 'selector' => '{{WRAPPER}} .plm-heading' ) );
		$this->add_responsive_control( 'heading_align', array( 'label' => esc_html__( 'تراز عنوان‌ها', 'parsi-logistics-map' ), 'type' => Controls_Manager::CHOOSE, 'options' => array( 'right' => array( 'title' => esc_html__( 'راست', 'parsi-logistics-map' ), 'icon' => 'eicon-text-align-right' ), 'center' => array( 'title' => esc_html__( 'وسط', 'parsi-logistics-map' ), 'icon' => 'eicon-text-align-center' ), 'left' => array( 'title' => esc_html__( 'چپ', 'parsi-logistics-map' ), 'icon' => 'eicon-text-align-left' ) ), 'default' => 'right', 'selectors' => array( '{{WRAPPER}} .plm-column-header' => 'text-align: {{VALUE}};' ) ) );
		$this->add_control( 'subtitle_color', array( 'label' => esc_html__( 'رنگ زیرعنوان', 'parsi-logistics-map' ), 'type' => Controls_Manager::COLOR, 'default' => '#2f2f2f', 'selectors' => array( '{{WRAPPER}} .plm-services-subtitle' => 'color: {{VALUE}};' ) ) );
		$this->add_group_control( Group_Control_Typography::get_type(), array( 'name' => 'subtitle_typography', 'selector' => '{{WRAPPER}} .plm-services-subtitle' ) );
		$this->end_controls_section();
	}

	/** Map appearance controls. */
	private function register_map_style_controls() {
		$this->start_controls_section( 'map_style', array( 'label' => esc_html__( 'ظاهر نقشه و مسیرها', 'parsi-logistics-map' ), 'tab' => Controls_Manager::TAB_STYLE ) );
		$this->add_responsive_control( 'map_max_width', array( 'label' => esc_html__( 'حداکثر عرض نقشه', 'parsi-logistics-map' ), 'type' => Controls_Manager::SLIDER, 'size_units' => array( 'px', '%' ), 'range' => array( 'px' => array( 'min' => 200, 'max' => 1200 ), '%' => array( 'min' => 30, 'max' => 100 ) ), 'default' => array( 'unit' => '%', 'size' => 100 ), 'selectors' => array( '{{WRAPPER}} .plm-map-stage' => 'max-width: {{SIZE}}{{UNIT}};' ) ) );
		$this->add_responsive_control( 'map_top_gap', array( 'label' => esc_html__( 'فاصله عنوان تا نقشه', 'parsi-logistics-map' ), 'type' => Controls_Manager::SLIDER, 'size_units' => array( 'px', 'em' ), 'range' => array( 'px' => array( 'min' => 0, 'max' => 100 ) ), 'default' => array( 'unit' => 'px', 'size' => 36 ), 'selectors' => array( '{{WRAPPER}} .plm-map-stage' => 'margin-top: {{SIZE}}{{UNIT}};' ) ) );
		$this->add_control( 'label_color', array( 'label' => esc_html__( 'رنگ برچسب‌ها', 'parsi-logistics-map' ), 'type' => Controls_Manager::COLOR, 'default' => '#222222', 'selectors' => array( '{{WRAPPER}} .plm-map-label' => 'color: {{VALUE}};' ) ) );
		$this->add_group_control( Group_Control_Typography::get_type(), array( 'name' => 'label_typography', 'selector' => '{{WRAPPER}} .plm-map-label' ) );
		$this->add_control( 'hub_color', array( 'label' => esc_html__( 'رنگ نقطه مرکزی', 'parsi-logistics-map' ), 'type' => Controls_Manager::COLOR, 'default' => '#b63b16', 'selectors' => array( '{{WRAPPER}} .plm-map-hub' => 'background-color: {{VALUE}}; box-shadow: 0 0 0 3px color-mix(in srgb, {{VALUE}} 24%, transparent);' ), 'condition' => array( 'show_hub' => 'yes' ) ) );
		$this->add_responsive_control( 'hub_size', array( 'label' => esc_html__( 'اندازه نقطه مرکزی', 'parsi-logistics-map' ), 'type' => Controls_Manager::SLIDER, 'size_units' => array( 'px' ), 'range' => array( 'px' => array( 'min' => 3, 'max' => 24 ) ), 'default' => array( 'unit' => 'px', 'size' => 9 ), 'selectors' => array( '{{WRAPPER}} .plm-map-hub' => 'width: {{SIZE}}{{UNIT}}; height: {{SIZE}}{{UNIT}};' ), 'condition' => array( 'show_hub' => 'yes' ) ) );
		$this->end_controls_section();
	}

	/** Service card appearance controls. */
	private function register_service_style_controls() {
		$this->start_controls_section( 'service_style', array( 'label' => esc_html__( 'ظاهر کارت‌های خدمات', 'parsi-logistics-map' ), 'tab' => Controls_Manager::TAB_STYLE ) );
		$this->add_responsive_control( 'cards_top_gap', array( 'label' => esc_html__( 'فاصله عنوان تا کارت‌ها', 'parsi-logistics-map' ), 'type' => Controls_Manager::SLIDER, 'size_units' => array( 'px', 'em' ), 'range' => array( 'px' => array( 'min' => 0, 'max' => 100 ) ), 'default' => array( 'unit' => 'px', 'size' => 34 ), 'selectors' => array( '{{WRAPPER}} .plm-services-list' => 'margin-top: {{SIZE}}{{UNIT}};' ) ) );
		$this->add_responsive_control( 'cards_gap', array( 'label' => esc_html__( 'فاصله میان کارت‌ها', 'parsi-logistics-map' ), 'type' => Controls_Manager::SLIDER, 'size_units' => array( 'px', 'em' ), 'range' => array( 'px' => array( 'min' => 0, 'max' => 60 ) ), 'default' => array( 'unit' => 'px', 'size' => 20 ), 'selectors' => array( '{{WRAPPER}} .plm-services-list' => 'gap: {{SIZE}}{{UNIT}};' ) ) );
		$this->add_group_control( Group_Control_Background::get_type(), array( 'name' => 'card_background', 'types' => array( 'classic', 'gradient' ), 'selector' => '{{WRAPPER}} .plm-service-card' ) );
		$this->add_responsive_control( 'card_padding', array( 'label' => esc_html__( 'فاصله داخلی کارت', 'parsi-logistics-map' ), 'type' => Controls_Manager::DIMENSIONS, 'size_units' => array( 'px', 'em' ), 'default' => array( 'top' => 24, 'right' => 24, 'bottom' => 24, 'left' => 24, 'unit' => 'px', 'isLinked' => true ), 'selectors' => array( '{{WRAPPER}} .plm-service-card' => 'padding: {{TOP}}{{UNIT}} {{RIGHT}}{{UNIT}} {{BOTTOM}}{{UNIT}} {{LEFT}}{{UNIT}};' ) ) );
		$this->add_group_control( Group_Control_Border::get_type(), array( 'name' => 'card_border', 'selector' => '{{WRAPPER}} .plm-service-card' ) );
		$this->add_responsive_control( 'card_radius', array( 'label' => esc_html__( 'گردی گوشه‌ها', 'parsi-logistics-map' ), 'type' => Controls_Manager::DIMENSIONS, 'size_units' => array( 'px', '%' ), 'default' => array( 'top' => 18, 'right' => 18, 'bottom' => 18, 'left' => 18, 'unit' => 'px', 'isLinked' => true ), 'selectors' => array( '{{WRAPPER}} .plm-service-card' => 'border-radius: {{TOP}}{{UNIT}} {{RIGHT}}{{UNIT}} {{BOTTOM}}{{UNIT}} {{LEFT}}{{UNIT}};' ) ) );
		$this->add_group_control( Group_Control_Box_Shadow::get_type(), array( 'name' => 'card_shadow', 'selector' => '{{WRAPPER}} .plm-service-card' ) );
		$this->add_control( 'service_title_color', array( 'label' => esc_html__( 'رنگ عنوان کارت', 'parsi-logistics-map' ), 'type' => Controls_Manager::COLOR, 'default' => '#b63b16', 'selectors' => array( '{{WRAPPER}} .plm-service-title' => 'color: {{VALUE}};' ) ) );
		$this->add_group_control( Group_Control_Typography::get_type(), array( 'name' => 'service_title_typography', 'selector' => '{{WRAPPER}} .plm-service-title' ) );
		$this->add_control( 'service_text_color', array( 'label' => esc_html__( 'رنگ توضیحات کارت', 'parsi-logistics-map' ), 'type' => Controls_Manager::COLOR, 'default' => '#303030', 'selectors' => array( '{{WRAPPER}} .plm-service-description' => 'color: {{VALUE}};' ) ) );
		$this->add_group_control( Group_Control_Typography::get_type(), array( 'name' => 'service_text_typography', 'selector' => '{{WRAPPER}} .plm-service-description' ) );
		$this->add_control( 'icon_color', array( 'label' => esc_html__( 'رنگ آیکن', 'parsi-logistics-map' ), 'type' => Controls_Manager::COLOR, 'default' => '#111111', 'selectors' => array( '{{WRAPPER}} .plm-service-icon' => 'color: {{VALUE}}; fill: {{VALUE}};' ) ) );
		$this->add_responsive_control( 'icon_size', array( 'label' => esc_html__( 'اندازه آیکن', 'parsi-logistics-map' ), 'type' => Controls_Manager::SLIDER, 'size_units' => array( 'px', 'em' ), 'range' => array( 'px' => array( 'min' => 12, 'max' => 90 ) ), 'default' => array( 'unit' => 'px', 'size' => 38 ), 'selectors' => array( '{{WRAPPER}} .plm-service-icon' => 'font-size: {{SIZE}}{{UNIT}}; width: {{SIZE}}{{UNIT}};' ) ) );
		$this->end_controls_section();
	}

	/** Keep percentage-like repeater values in a safe range. */
	private function coordinate( $value, $scale = 1 ) {
		$value = is_numeric( $value ) ? (float) $value : 0;
		return max( -50, min( 150, $value ) ) * $scale;
	}

	/** Output the final widget. */
	protected function render() {
		$settings = $this->get_settings_for_display();
		$map_url  = ! empty( $settings['map_image']['url'] ) ? $settings['map_image']['url'] : '';
		?>
		<section class="plm-widget" dir="rtl" aria-label="<?php echo esc_attr( $settings['map_title'] ); ?>">
			<div class="plm-map-column">
				<header class="plm-column-header">
					<?php if ( ! empty( $settings['map_title'] ) ) : ?>
						<h2 class="plm-heading plm-map-title"><?php echo esc_html( $settings['map_title'] ); ?></h2>
					<?php endif; ?>
				</header>

				<?php if ( $map_url ) : ?>
					<div class="plm-map-stage">
						<img class="plm-map-image" src="<?php echo esc_url( $map_url ); ?>" alt="<?php echo esc_attr( $settings['map_alt'] ); ?>" loading="lazy">
						<svg class="plm-route-layer" viewBox="0 0 1000 508" preserveAspectRatio="none" aria-hidden="true" focusable="false">
							<defs>
								<?php foreach ( $settings['routes'] as $index => $route ) :
									$marker_id = 'plm-arrow-' . $this->get_id() . '-' . (int) $index;
									$color     = ! empty( $route['route_color'] ) ? $route['route_color'] : '#b63b16';
									?>
									<marker id="<?php echo esc_attr( $marker_id ); ?>" markerWidth="5" markerHeight="5" refX="4.1" refY="2.5" orient="auto" markerUnits="strokeWidth">
										<path d="M0,0 L5,2.5 L0,5 Z" fill="<?php echo esc_attr( $color ); ?>"></path>
									</marker>
								<?php endforeach; ?>
							</defs>
							<?php foreach ( $settings['routes'] as $index => $route ) :
								$x1        = $this->coordinate( $route['start_x'], 10 );
								$y1        = $this->coordinate( $route['start_y'], 5.08 );
								$cx        = $this->coordinate( $route['control_x'], 10 );
								$cy        = $this->coordinate( $route['control_y'], 5.08 );
								$x2        = $this->coordinate( $route['end_x'], 10 );
								$y2        = $this->coordinate( $route['end_y'], 5.08 );
								$color     = ! empty( $route['route_color'] ) ? $route['route_color'] : '#b63b16';
								$width     = isset( $route['route_width'] ) ? max( 0.5, min( 10, (float) $route['route_width'] ) ) : 2.4;
								$marker_id = 'plm-arrow-' . $this->get_id() . '-' . (int) $index;
								?>
								<path class="plm-route" d="M <?php echo esc_attr( $x1 . ' ' . $y1 . ' Q ' . $cx . ' ' . $cy . ' ' . $x2 . ' ' . $y2 ); ?>" fill="none" stroke="<?php echo esc_attr( $color ); ?>" stroke-width="<?php echo esc_attr( $width ); ?>"<?php echo ( 'yes' === $route['show_arrow'] ) ? ' marker-end="url(#' . esc_attr( $marker_id ) . ')"' : ''; ?>></path>
							<?php endforeach; ?>
						</svg>

						<?php if ( 'yes' === $settings['show_hub'] ) : ?>
							<span class="plm-map-hub" aria-hidden="true"></span>
						<?php endif; ?>

						<?php foreach ( $settings['map_labels'] as $label ) :
							$label_x = max( 0, min( 100, (float) $label['x'] ) );
							$label_y = max( 0, min( 100, (float) $label['y'] ) );
							$align   = in_array( $label['align'], array( 'right', 'center', 'left' ), true ) ? $label['align'] : 'center';
							?>
							<span class="plm-map-label plm-label-<?php echo esc_attr( $align ); ?>" style="left:<?php echo esc_attr( $label_x ); ?>%;top:<?php echo esc_attr( $label_y ); ?>%;"><?php echo esc_html( $label['text'] ); ?></span>
						<?php endforeach; ?>
					</div>
				<?php endif; ?>
			</div>

			<div class="plm-services-column">
				<header class="plm-column-header">
					<?php if ( ! empty( $settings['services_title'] ) ) : ?>
						<h2 class="plm-heading plm-services-title"><?php echo esc_html( $settings['services_title'] ); ?></h2>
					<?php endif; ?>
					<?php if ( ! empty( $settings['services_subtitle'] ) ) : ?>
						<p class="plm-services-subtitle"><?php echo esc_html( $settings['services_subtitle'] ); ?></p>
					<?php endif; ?>
				</header>

				<div class="plm-services-list">
					<?php foreach ( $settings['services'] as $index => $service ) :
						$has_link = ! empty( $service['link']['url'] );
						if ( $has_link ) {
							$this->add_link_attributes( 'service-link-' . $index, $service['link'] );
						}
						?>
						<article class="plm-service-card elementor-repeater-item-<?php echo esc_attr( $service['_id'] ); ?>">
							<?php if ( $has_link ) : ?>
								<a class="plm-service-inner" <?php $this->print_render_attribute_string( 'service-link-' . $index ); ?>>
							<?php else : ?>
								<div class="plm-service-inner">
							<?php endif; ?>
								<?php if ( ! empty( $service['selected_icon']['value'] ) ) : ?>
									<div class="plm-service-icon" aria-hidden="true"><?php Icons_Manager::render_icon( $service['selected_icon'], array( 'aria-hidden' => 'true' ) ); ?></div>
								<?php endif; ?>
								<div class="plm-service-copy">
									<?php if ( ! empty( $service['title'] ) ) : ?><h3 class="plm-service-title"><?php echo esc_html( $service['title'] ); ?></h3><?php endif; ?>
									<?php if ( ! empty( $service['description'] ) ) : ?><div class="plm-service-description"><?php echo wp_kses_post( wpautop( $service['description'] ) ); ?></div><?php endif; ?>
								</div>
							<?php if ( $has_link ) : ?>
								</a>
							<?php else : ?>
								</div>
							<?php endif; ?>
						</article>
					<?php endforeach; ?>
				</div>
			</div>
		</section>
		<?php
	}
}
